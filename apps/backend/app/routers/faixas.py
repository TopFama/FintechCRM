from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from .. import models, regras_db, schemas
from ..database import get_db
from ..deps import get_current_user
from ..utils.spreadsheet import build_model_xlsx

router = APIRouter(prefix="/faixas", tags=["faixas"])


def _full_query(db: Session):
    return db.query(models.Faixa).options(
        selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.whatsapp_number),
        selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.template).selectinload(
            models.Template.variables
        ),
        selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.dispatch_config),
        selectinload(models.Faixa.variable_mappings),
    )


def _validar_mapeamento_variaveis(template: models.Template, variable_mappings: list) -> None:
    template_variable_ids = {v.id for v in template.variables}
    mapped_ids = {m.template_variable_id for m in variable_mappings}
    if template_variable_ids != mapped_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Toda variável do template precisa de uma coluna de planilha mapeada",
        )


def _salvar_mapeamento(
    db: Session, faixa_id: str, template: models.Template, variable_mappings: list
) -> None:
    """Substitui o mapeamento de variáveis do par (faixa, template) — usado
    por todos os envios dessa faixa que usam esse template."""

    _validar_mapeamento_variaveis(template, variable_mappings)
    db.query(models.FaixaVariableMapping).filter(
        models.FaixaVariableMapping.faixa_id == faixa_id,
        models.FaixaVariableMapping.template_id == template.id,
    ).delete()
    for mapping in variable_mappings:
        db.add(
            models.FaixaVariableMapping(
                faixa_id=faixa_id,
                template_id=template.id,
                template_variable_id=mapping.template_variable_id,
                fonte_tipo=mapping.fonte_tipo,
                column_name=mapping.column_name,
                expressao=mapping.expressao,
            )
        )


def _tem_mapeamento(db: Session, faixa_id: str, template_id: str) -> bool:
    return (
        db.query(models.FaixaVariableMapping.id)
        .filter(
            models.FaixaVariableMapping.faixa_id == faixa_id,
            models.FaixaVariableMapping.template_id == template_id,
        )
        .first()
        is not None
    )


def _get_template(db: Session, template_id: str, exigir_aprovado: bool = True) -> models.Template:
    template = (
        db.query(models.Template)
        .options(selectinload(models.Template.variables))
        .filter(models.Template.id == template_id)
        .first()
    )
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
    if exigir_aprovado and template.status != models.TemplateStatus.approved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Só é possível usar template aprovado pela Meta"
        )
    return template


def _get_faixa(db: Session, faixa_id: str) -> models.Faixa:
    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    return faixa


@router.get("", response_model=list[schemas.FaixaOut])
def list_faixas(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return (
        _full_query(db)
        .filter(models.Faixa.active.is_(True))
        .order_by(models.Faixa.created_at.desc())
        .all()
    )


@router.get("/{faixa_id}", response_model=schemas.FaixaOut)
def get_faixa(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    faixa = _full_query(db).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    return faixa


@router.post("", response_model=schemas.FaixaOut, status_code=status.HTTP_201_CREATED)
def create_faixa(
    payload: schemas.FaixaCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    if db.query(models.Faixa).filter(models.Faixa.name == payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma faixa com esse nome")

    faixa = models.Faixa(name=payload.name)
    db.add(faixa)
    db.flush()

    if payload.template_id:
        template = _get_template(db, payload.template_id)
        _salvar_mapeamento(db, faixa.id, template, payload.variable_mappings)

        for number_id in payload.whatsapp_number_ids:
            number = db.query(models.WhatsappNumber).filter(models.WhatsappNumber.id == number_id).first()
            if not number:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Número {number_id} não encontrado")
            envio = models.FaixaEnvio(faixa_id=faixa.id, whatsapp_number_id=number_id, template_id=template.id)
            db.add(envio)
            db.flush()
            db.add(models.DispatchConfig(faixa_envio_id=envio.id, active=False))

    db.commit()
    return _full_query(db).filter(models.Faixa.id == faixa.id).first()


@router.post("/sincronizar-faixas-atraso", response_model=schemas.SincronizarFaixasAtrasoOut)
def sincronizar_faixas_atraso(
    db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    """Cria uma faixa de cobrança (aba "Faixas") para cada faixa de atraso
    configurada em Configurações → Regras de cobrança que ainda não tenha
    uma faixa de cobrança com o mesmo nome. A faixa nasce sem nenhum envio
    (número + template) — atribua ao menos um em "Faixas" antes de ligar o
    disparo."""

    regras = regras_db.carregar_regras(db)
    nomes_existentes = {f.name for f in db.query(models.Faixa.name).all()}

    criadas: list[str] = []
    ja_existentes: list[str] = []
    for nome in regras.nomes_faixa:
        if nome in nomes_existentes:
            ja_existentes.append(nome)
            continue
        db.add(models.Faixa(name=nome))
        criadas.append(nome)
        nomes_existentes.add(nome)

    db.commit()
    return schemas.SincronizarFaixasAtrasoOut(criadas=criadas, ja_existentes=ja_existentes)


@router.post(
    "/{faixa_id}/envios", response_model=schemas.FaixaEnvioOut, status_code=status.HTTP_201_CREATED
)
def add_envio(
    faixa_id: str,
    payload: schemas.FaixaEnvioCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Atribui mais um par (número, template) a uma faixa já existente —
    cada um roda com seu próprio agendamento (ver dispatch-config), pensado
    pra números de WABAs diferentes cobrando em paralelo."""

    faixa = _get_faixa(db, faixa_id)
    template = _get_template(db, payload.template_id)
    number = db.query(models.WhatsappNumber).filter(models.WhatsappNumber.id == payload.whatsapp_number_id).first()
    if not number:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Número não encontrado")

    ja_existe = (
        db.query(models.FaixaEnvio)
        .filter(
            models.FaixaEnvio.faixa_id == faixa_id,
            models.FaixaEnvio.whatsapp_number_id == payload.whatsapp_number_id,
        )
        .first()
    )
    if ja_existe:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este número já está atribuído a esta faixa")

    if payload.variable_mappings:
        _salvar_mapeamento(db, faixa_id, template, payload.variable_mappings)
    elif template.variables and not _tem_mapeamento(db, faixa_id, template.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Mapeie as variáveis deste template antes de usá-lo nesta faixa",
        )

    envio = models.FaixaEnvio(faixa_id=faixa_id, whatsapp_number_id=payload.whatsapp_number_id, template_id=template.id)
    db.add(envio)
    db.flush()
    # Numa campanha ou segmento de remarketing, quem decide se roda é a
    # própria campanha/segmento (ligado, dia, período): o disparo já nasce ligado.
    tem_regra_propria = (
        db.query(models.Campanha.id).filter(models.Campanha.faixa_id == faixa_id).first()
        or db.query(models.RemarketingSegmento.segmento).filter(models.RemarketingSegmento.faixa_id == faixa_id).first()
    )
    db.add(models.DispatchConfig(faixa_envio_id=envio.id, active=tem_regra_propria is not None))
    db.commit()

    return (
        db.query(models.FaixaEnvio)
        .options(
            selectinload(models.FaixaEnvio.whatsapp_number),
            selectinload(models.FaixaEnvio.template).selectinload(models.Template.variables),
            selectinload(models.FaixaEnvio.dispatch_config),
        )
        .filter(models.FaixaEnvio.id == envio.id)
        .first()
    )


@router.put("/{faixa_id}/envios/{envio_id}", response_model=schemas.FaixaEnvioOut)
def update_envio(
    faixa_id: str,
    envio_id: str,
    payload: schemas.FaixaEnvioUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    envio = (
        db.query(models.FaixaEnvio)
        .filter(models.FaixaEnvio.id == envio_id, models.FaixaEnvio.faixa_id == faixa_id)
        .first()
    )
    if not envio:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Envio não encontrado")

    # Envio que já usava o template continua editável mesmo se ele deixar de ser aprovado
    template = _get_template(db, payload.template_id, exigir_aprovado=payload.template_id != envio.template_id)
    number = db.query(models.WhatsappNumber).filter(models.WhatsappNumber.id == payload.whatsapp_number_id).first()
    if not number:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Número não encontrado")

    conflito = (
        db.query(models.FaixaEnvio)
        .filter(
            models.FaixaEnvio.faixa_id == faixa_id,
            models.FaixaEnvio.whatsapp_number_id == payload.whatsapp_number_id,
            models.FaixaEnvio.id != envio_id,
        )
        .first()
    )
    if conflito:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este número já está atribuído a esta faixa")

    if payload.variable_mappings:
        _salvar_mapeamento(db, faixa_id, template, payload.variable_mappings)
    elif template.variables and not _tem_mapeamento(db, faixa_id, template.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Mapeie as variáveis deste template antes de usá-lo nesta faixa",
        )

    envio.whatsapp_number_id = payload.whatsapp_number_id
    envio.template_id = payload.template_id
    envio.active = payload.active
    if not payload.active and envio.dispatch_config:
        envio.dispatch_config.active = False
    db.commit()

    return (
        db.query(models.FaixaEnvio)
        .options(
            selectinload(models.FaixaEnvio.whatsapp_number),
            selectinload(models.FaixaEnvio.template).selectinload(models.Template.variables),
            selectinload(models.FaixaEnvio.dispatch_config),
        )
        .filter(models.FaixaEnvio.id == envio_id)
        .first()
    )


@router.delete("/{faixa_id}/envios/{envio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_envio(
    faixa_id: str, envio_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    envio = (
        db.query(models.FaixaEnvio)
        .filter(models.FaixaEnvio.id == envio_id, models.FaixaEnvio.faixa_id == faixa_id)
        .first()
    )
    if not envio:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Envio não encontrado")
    db.delete(envio)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{faixa_id}/spreadsheet-model")
def download_spreadsheet_model(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    faixa = _full_query(db).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    if not faixa.variable_mappings:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Faixa sem template atribuído")
    variable_names = [m.template_variable.internal_name for m in faixa.variable_mappings]
    content = build_model_xlsx(variable_names)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            # Nome com acento, travessão ou aspas: filename* em UTF-8 e um nome ASCII de reserva
            "Content-Disposition": (
                f'attachment; filename="modelo.xlsx"; filename*=UTF-8\'\'{quote(f"modelo_{faixa.name}.xlsx")}'
            )
        },
    )


@router.put("/{faixa_id}/envios/{envio_id}/dispatch-config", response_model=schemas.DispatchConfigOut)
def update_dispatch_config(
    faixa_id: str,
    envio_id: str,
    payload: schemas.DispatchConfigUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    envio = (
        db.query(models.FaixaEnvio)
        .filter(models.FaixaEnvio.id == envio_id, models.FaixaEnvio.faixa_id == faixa_id)
        .first()
    )
    if not envio:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Envio não encontrado")
    if payload.active and not envio.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este envio está desativado — reative-o antes de ligar o disparo")
    config = db.query(models.DispatchConfig).filter(models.DispatchConfig.faixa_envio_id == envio_id).first()
    if not config:
        config = models.DispatchConfig(faixa_envio_id=envio_id)
        db.add(config)
    for field, value in payload.model_dump().items():
        setattr(config, field, value)
    db.commit()
    db.refresh(config)
    return config


@router.delete("/{faixa_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_faixa(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    """Exclusão lógica: preserva o histórico de envios/relatórios já ligados a
    esta faixa (cobranca_fila, telefones_invalidos etc. referenciam faixa_id),
    só tira a faixa da lista e para qualquer disparo agendado nela."""

    if db.query(models.RemarketingSegmento).filter(models.RemarketingSegmento.faixa_id == faixa_id).first():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Faixa de remarketing não pode ser excluída; desligue o segmento em Remarketing"
        )
    faixa = (
        db.query(models.Faixa)
        .options(selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.dispatch_config))
        .filter(models.Faixa.id == faixa_id)
        .first()
    )
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    faixa.active = False
    for envio in faixa.envios:
        if envio.dispatch_config:
            envio.dispatch_config.active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{faixa_id}/dispatch-now", status_code=status.HTTP_202_ACCEPTED)
def dispatch_now(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    """Marca todos os envios ativos desta faixa para serem processados pelo
    worker na próxima varredura, ignorando o agendamento configurado —
    equivalente ao antigo 'cobrar agora'."""

    faixa = (
        db.query(models.Faixa)
        .options(selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.dispatch_config))
        .filter(models.Faixa.id == faixa_id)
        .first()
    )
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    envios_ativos = [e for e in faixa.envios if e.active and e.dispatch_config]
    if not envios_ativos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Faixa sem número/template ativo para disparar")
    for envio in envios_ativos:
        envio.dispatch_config.force_run = True
    db.commit()
    return {"status": "agendado para a próxima varredura do worker"}
