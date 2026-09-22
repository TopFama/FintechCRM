from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from .. import models, regras_db, schemas
from ..database import get_db
from ..deps import get_current_user
from ..utils.spreadsheet import build_model_xlsx

router = APIRouter(prefix="/faixas", tags=["faixas"])


def _full_query(db: Session):
    return db.query(models.Faixa).options(
        selectinload(models.Faixa.template).selectinload(models.Template.variables),
        selectinload(models.Faixa.numbers),
        selectinload(models.Faixa.variable_mappings),
        selectinload(models.Faixa.dispatch_config),
    )


def _validar_mapeamento_variaveis(template: models.Template, variable_mappings: list) -> None:
    template_variable_ids = {v.id for v in template.variables}
    mapped_ids = {m.template_variable_id for m in variable_mappings}
    if template_variable_ids != mapped_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Toda variável do template precisa de uma coluna de planilha mapeada",
        )


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
    template = (
        db.query(models.Template)
        .options(selectinload(models.Template.variables))
        .filter(models.Template.id == payload.template_id)
        .first()
    )
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
    if db.query(models.Faixa).filter(models.Faixa.name == payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma faixa com esse nome")
    if not payload.whatsapp_number_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selecione ao menos um número de envio")

    _validar_mapeamento_variaveis(template, payload.variable_mappings)

    faixa = models.Faixa(name=payload.name, template_id=payload.template_id)
    db.add(faixa)
    db.flush()

    for number_id in payload.whatsapp_number_ids:
        number = db.query(models.WhatsappNumber).get(number_id)
        if not number:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Número {number_id} não encontrado")
        db.add(models.FaixaNumber(faixa_id=faixa.id, whatsapp_number_id=number_id))

    for mapping in payload.variable_mappings:
        db.add(
            models.FaixaVariableMapping(
                faixa_id=faixa.id,
                template_variable_id=mapping.template_variable_id,
                fonte_tipo=mapping.fonte_tipo,
                column_name=mapping.column_name,
                expressao=mapping.expressao,
            )
        )

    db.add(models.DispatchConfig(faixa_id=faixa.id, active=False))

    db.commit()
    return _full_query(db).filter(models.Faixa.id == faixa.id).first()


@router.post("/sincronizar-faixas-atraso", response_model=schemas.SincronizarFaixasAtrasoOut)
def sincronizar_faixas_atraso(
    db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    """Cria uma faixa de cobrança (aba "Faixas") para cada faixa de atraso
    configurada em Configurações → Regras de cobrança que ainda não tenha
    uma faixa de cobrança com o mesmo nome. A faixa nasce sem template, sem
    número e sem mapeamento de variável — completar isso em "Faixas" antes
    de ligar o disparo."""

    regras = regras_db.carregar_regras(db)
    nomes_existentes = {f.name for f in db.query(models.Faixa.name).all()}

    criadas: list[str] = []
    ja_existentes: list[str] = []
    for nome in regras.nomes_faixa:
        if nome in nomes_existentes:
            ja_existentes.append(nome)
            continue
        faixa = models.Faixa(name=nome, template_id=None)
        db.add(faixa)
        db.flush()
        db.add(models.DispatchConfig(faixa_id=faixa.id, active=False))
        criadas.append(nome)
        nomes_existentes.add(nome)

    db.commit()
    return schemas.SincronizarFaixasAtrasoOut(criadas=criadas, ja_existentes=ja_existentes)


@router.put("/{faixa_id}", response_model=schemas.FaixaOut)
def update_faixa(
    faixa_id: str,
    payload: schemas.FaixaUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Reatribui template, números de envio e mapeamento de variáveis de uma
    faixa já existente — o nome não muda. template_id None deixa a faixa sem
    template (disparo fica pausado)."""

    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")

    template = None
    if payload.template_id is not None:
        template = (
            db.query(models.Template)
            .options(selectinload(models.Template.variables))
            .filter(models.Template.id == payload.template_id)
            .first()
        )
        if not template:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
        _validar_mapeamento_variaveis(template, payload.variable_mappings)
    elif payload.variable_mappings:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Não é possível mapear variáveis sem um template atribuído"
        )

    for number_id in payload.whatsapp_number_ids:
        if not db.query(models.WhatsappNumber).filter(models.WhatsappNumber.id == number_id).first():
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Número {number_id} não encontrado")

    faixa.template_id = payload.template_id
    faixa.last_number_index = 0

    db.query(models.FaixaNumber).filter(models.FaixaNumber.faixa_id == faixa.id).delete()
    for number_id in payload.whatsapp_number_ids:
        db.add(models.FaixaNumber(faixa_id=faixa.id, whatsapp_number_id=number_id))

    db.query(models.FaixaVariableMapping).filter(models.FaixaVariableMapping.faixa_id == faixa.id).delete()
    for mapping in payload.variable_mappings:
        db.add(
            models.FaixaVariableMapping(
                faixa_id=faixa.id,
                template_variable_id=mapping.template_variable_id,
                fonte_tipo=mapping.fonte_tipo,
                column_name=mapping.column_name,
                expressao=mapping.expressao,
            )
        )

    # Template mudou (ou sumiu): não dá mais pra confiar no mapeamento de
    # colunas da planilha anterior, já que as variáveis podem ser outras.
    faixa.upload_field_mapping = {}

    config = db.query(models.DispatchConfig).filter(models.DispatchConfig.faixa_id == faixa.id).first()
    if config and payload.template_id is None:
        config.active = False

    db.commit()
    return _full_query(db).filter(models.Faixa.id == faixa.id).first()


@router.get("/{faixa_id}/spreadsheet-model")
def download_spreadsheet_model(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    faixa = _full_query(db).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    if not faixa.template:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Faixa sem template atribuído")
    variable_names = [
        next(v.internal_name for v in faixa.template.variables if v.id == m.template_variable_id)
        for m in faixa.variable_mappings
    ]
    content = build_model_xlsx(variable_names)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="modelo_{faixa.name}.xlsx"'
        },
    )


@router.put("/{faixa_id}/dispatch-config", response_model=schemas.DispatchConfigOut)
def update_dispatch_config(
    faixa_id: str,
    payload: schemas.DispatchConfigUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    if payload.active and not faixa.template_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Atribua um template à faixa antes de ativar o disparo")
    config = db.query(models.DispatchConfig).filter(models.DispatchConfig.faixa_id == faixa_id).first()
    if not config:
        config = models.DispatchConfig(faixa_id=faixa_id)
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

    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    faixa.active = False
    config = db.query(models.DispatchConfig).filter(models.DispatchConfig.faixa_id == faixa_id).first()
    if config:
        config.active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{faixa_id}/dispatch-now", status_code=status.HTTP_202_ACCEPTED)
def dispatch_now(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    """Marca a faixa para ser processada pelo worker na próxima varredura,
    ignorando o agendamento configurado — equivalente ao antigo 'cobrar agora'."""

    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    if not faixa.template_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Atribua um template à faixa antes de disparar")
    config = db.query(models.DispatchConfig).filter(models.DispatchConfig.faixa_id == faixa_id).first()
    if not config:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa sem configuração de disparo")
    config.force_run = True
    db.commit()
    return {"status": "agendado para a próxima varredura do worker"}
