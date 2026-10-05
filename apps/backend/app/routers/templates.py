import asyncio
import logging
import os
import re
import time
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session, selectinload

from .. import chatwoot_client, models, schemas
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..dispatch_service import arquivo_imagem, media_id_da_imagem, montar_parametros_envio
from ..meta_client import MetaAPIError, MetaClient, MetaTokenConfigError, token_da_waba, token_do_numero
from ..utils import imagem
from ..utils.erros import descrever_erro_envio
from ..utils.phone import is_valid_phone, normalize_phone
from ..variaveis_template import CAMPOS_CLIENTE, contexto_cliente

router = APIRouter(prefix="/templates", tags=["templates"])
logger = logging.getLogger(__name__)

# Cabeçalho de imagem do template: o arquivo é conferido e, se preciso,
# comprimido para o limite da Meta (utils/imagem.py). Fica em /media, servido
# publicamente sem autenticação.
_EXTENSOES_IMAGEM_PERMITIDAS = {".jpg", ".jpeg", ".png", ".webp"}
# Versão comprimida esperando o usuário aprovar; some sozinha depois de 1 h
_PASTA_PENDENTES = "pendentes"
_VALIDADE_PENDENTE_SEGUNDOS = 3600
_TOKEN_PENDENTE = re.compile(r"^(?P<template>[0-9a-f-]{1,64})-[0-9a-f]{32}\.(jpg|png)$")


def _with_variables(query):
    return query.options(selectinload(models.Template.variables))


@router.get("", response_model=list[schemas.TemplateOut])
def list_templates(
    db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    return _with_variables(db.query(models.Template)).order_by(
        models.Template.created_at.desc()
    ).all()


CLIENTE_EXEMPLO = {
    "codigo": "123456",
    "nome": "Maria da Silva Santos",
    "cpfcnpj": "12345678901",
    "celular": "5511999998888",
    "cluster": "ESPECIAL",
    "faixa": "11 A 20",
    "dias_atraso": 15,
    "qtd_parcelas_cobranca": 2,
    "valor_em_aberto": Decimal("1200.00"),
    "vencimento_mais_antigo": date(2026, 9, 21),
    "valor_parcela_amanha": Decimal("189.90"),
    "valor_atraso": Decimal("1100.00"),
}


@router.get("/variaveis/campos", response_model=list[schemas.CampoClienteOut])
def list_template_variable_fields(_user: models.User = Depends(get_current_user)):
    ctx = contexto_cliente(CLIENTE_EXEMPLO)
    return [
        schemas.CampoClienteOut(
            campo=campo,
            rotulo=rotulo,
            exemplo=ctx.get(campo, ""),
        )
        for campo, rotulo in CAMPOS_CLIENTE.items()
    ]


@router.patch("/{template_id}/variaveis/{variavel_id}", response_model=schemas.TemplateVariableOut)
def update_template_variable(
    template_id: str,
    variavel_id: str,
    payload: schemas.TemplateVariableUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    variavel = (
        db.query(models.TemplateVariable)
        .filter(models.TemplateVariable.id == variavel_id, models.TemplateVariable.template_id == template_id)
        .first()
    )
    if not variavel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variável não encontrada")
    variavel.campo_sugerido = payload.campo_sugerido
    db.commit()
    db.refresh(variavel)
    return variavel


@router.post("/meta/sync", response_model=list[schemas.TemplateOut])
async def sync_from_meta(
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Puxa os templates aprovados/pendentes direto da Meta e faz upsert local,
    para que o cadastro de faixa sempre escolha a partir do que existe na Meta.
    Não pede o WABA ID na mão: sincroniza as WABAs dos tokens ativos
    (Configurações) e dos números ativos (Números). Uma WABA com problema não
    impede as demais; só falha se nenhuma sincronizar."""

    waba_ids = sorted(
        {w for (w,) in db.query(models.MetaToken.waba_id).filter(models.MetaToken.ativo.is_(True)) if w}
        | {
            w
            for (w,) in db.query(models.WhatsappNumber.waba_id).filter(models.WhatsappNumber.active.is_(True))
            if w
        }
    )
    if not waba_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cadastre um token da Meta com a WABA (Configurações) antes de sincronizar templates",
        )

    falhas: list[str] = []
    for waba_id in waba_ids:
        try:
            client = MetaClient(access_token=token_da_waba(db, waba_id))
            remote_templates = await client.list_templates(waba_id)
        except Exception as exc:  # noqa: BLE001 - WABA fora do ar (timeout, 5xx em HTML) não impede as outras
            falhas.append(f"WABA {waba_id}: {exc}")
            logger.warning("Sincronização de templates pulou a WABA %s: %s", waba_id, exc)
            continue

        for remote in remote_templates:
            language = remote.get("language")
            if not language:
                falhas.append(
                    f"Template '{remote.get('name')}' na WABA {waba_id} não informou o idioma — cadastre o idioma manualmente"
                )
                logger.warning("Template %s na WABA %s sem idioma retornado pela Meta", remote.get("name"), waba_id)
                continue

            remote_id = remote.get("id")
            existing = None
            if remote_id:
                existing = (
                    db.query(models.Template)
                    .filter(models.Template.meta_template_id == remote_id)
                    .first()
                )
            if not existing:
                existing = (
                    db.query(models.Template)
                    .filter(
                        models.Template.waba_id == waba_id,
                        models.Template.meta_template_name == remote["name"],
                        models.Template.language == language,
                    )
                    .first()
                )
            if not existing:
                existing = (
                    db.query(models.Template)
                    .filter(
                        models.Template.waba_id == waba_id,
                        models.Template.meta_template_name == remote["name"],
                    )
                    .first()
                )

            status_value = _map_meta_status(remote.get("status"))
            header_type = _extract_header_type(remote)
            body_text = _extract_body_text(remote)

            if existing:
                existing.status = status_value
                existing.meta_status_raw = remote.get("status")
                existing.meta_template_id = remote_id
                existing.category = remote.get("category", existing.category)
                existing.waba_id = waba_id
                existing.header_type = header_type
                existing.language = language
                existing.body_text = body_text

                # Sincroniza variáveis com o texto atualizado do template
                posicoes_remotas = set()
                for i, name in enumerate(_extract_variable_count(remote), start=1):
                    posicoes_remotas.add(i)
                    var_existente = next((v for v in existing.variables if v.position == i), None)
                    if not var_existente:
                        db.add(
                            models.TemplateVariable(
                                template_id=existing.id, position=i, internal_name=name
                            )
                        )
                for v in list(existing.variables):
                    if v.position not in posicoes_remotas:
                        db.delete(v)
            else:
                template = models.Template(
                    name=remote["name"],
                    meta_template_name=remote["name"],
                    language=language,
                    category=remote.get("category", "UTILITY"),
                    header_type=header_type,
                    status=status_value,
                    meta_status_raw=remote.get("status"),
                    meta_template_id=remote_id,
                    waba_id=waba_id,
                    body_text=body_text,
                )
                db.add(template)
                db.flush()
                for i, name in enumerate(_extract_variable_count(remote), start=1):
                    db.add(
                        models.TemplateVariable(
                            template_id=template.id, position=i, internal_name=name
                        )
                    )
    if len(falhas) == len(waba_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Nenhuma WABA sincronizou — " + "; ".join(falhas)
        )
    db.commit()
    return _with_variables(db.query(models.Template)).order_by(
        models.Template.created_at.desc()
    ).all()


def _map_meta_status(raw: str | None) -> models.TemplateStatus:
    mapping = {
        "APPROVED": models.TemplateStatus.approved,
        "PENDING": models.TemplateStatus.pending,
        "REJECTED": models.TemplateStatus.rejected,
    }
    return mapping.get((raw or "").upper(), models.TemplateStatus.draft)


def _extract_body_text(remote: dict) -> str:
    for component in remote.get("components", []):
        if component.get("type") == "BODY":
            return component.get("text", "")
    return ""


def _extract_variable_count(remote: dict) -> list[str]:
    body_text = _extract_body_text(remote)
    import re

    positions = sorted({int(m) for m in re.findall(r"\{\{(\d+)\}\}", body_text)})
    return [f"variavel_{p}" for p in positions]


def _extract_header_type(remote: dict) -> models.TemplateHeaderType:
    """Detecta se o template já tem cabeçalho de mídia (imagem) na Meta —
    é isso que decide se a opção de atribuir imagem aparece pra esse
    template na aba Templates."""

    for component in remote.get("components", []):
        if component.get("type") == "HEADER" and component.get("format") == "IMAGE":
            return models.TemplateHeaderType.image
    return models.TemplateHeaderType.none


def _resolve_waba_id(db: Session, waba_id: str | None) -> str:
    """Resolve o WABA ID sem exigir digitação manual: usa o informado (quando
    a aba de Números tem mais de um WABA cadastrado) ou o único já existente."""

    if waba_id:
        return waba_id
    waba_ids = sorted(
        {row[0] for row in db.query(models.WhatsappNumber.waba_id).distinct().all() if row[0]}
    )
    if not waba_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Importe um número de WhatsApp (Configurações → Tokens da Meta) antes de criar um template",
        )
    if len(waba_ids) > 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Existe mais de um WABA cadastrado — escolha um na lista de Números",
        )
    return waba_ids[0]


# Todo template criado na plataforma é em português; os sincronizados da Meta
# mantêm o idioma que vier de lá.
IDIOMA_TEMPLATE = "pt_BR"


@router.post("", response_model=schemas.TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: schemas.TemplateCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Salva o template como rascunho; a Meta só recebe pelo
    `POST /{id}/enviar-para-aprovacao`, depois da imagem do cabeçalho."""

    waba_id = _resolve_waba_id(db, payload.waba_id)
    repetido = (
        db.query(models.Template.id)
        .filter(
            models.Template.waba_id == waba_id,
            models.Template.meta_template_name == payload.meta_template_name,
            models.Template.language == IDIOMA_TEMPLATE,
        )
        .first()
    )
    if repetido:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um template com esse nome nesta WABA")

    template = models.Template(
        name=payload.name,
        meta_template_name=payload.meta_template_name,
        language=IDIOMA_TEMPLATE,
        category=payload.category,
        header_type=payload.header_type,
        body_text=payload.body_text,
        waba_id=waba_id,
        status=models.TemplateStatus.draft,
    )
    db.add(template)
    db.flush()
    for var in payload.variables:
        db.add(
            models.TemplateVariable(
                template_id=template.id,
                position=var.position,
                internal_name=var.internal_name,
                campo_sugerido=var.campo_sugerido,
                exemplo=(var.exemplo or "").strip() or None,
            )
        )
    db.commit()
    return _with_variables(db.query(models.Template)).filter(models.Template.id == template.id).first()


@router.post("/{template_id}/enviar-para-aprovacao", response_model=schemas.TemplateOut)
async def enviar_para_aprovacao(
    template_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Cadastra o rascunho na Meta com os exemplos que a análise exige: o valor
    de cada variável (example.body_text) e, com cabeçalho de imagem, a imagem
    já subida no template (example.header_handle)."""

    template = _with_variables(db.query(models.Template)).filter(
        models.Template.id == template_id
    ).first()
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
    if template.meta_template_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este template já foi enviado para a Meta")
    if not template.waba_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "WABA não identificada para este template")
    if any(not v.exemplo for v in template.variables):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Preencha o exemplo de todas as variáveis antes de enviar para aprovação"
        )
    caminho_imagem = None
    if template.header_type == models.TemplateHeaderType.image:
        caminho_imagem = arquivo_imagem(template)
        if not caminho_imagem:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Suba a imagem do cabeçalho antes de enviar para aprovação"
            )

    try:
        client = MetaClient(access_token=token_da_waba(db, template.waba_id))
    except MetaTokenConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    corpo: dict = {"type": "BODY", "text": template.body_text}
    if template.variables:
        corpo["example"] = {"body_text": [[v.exemplo for v in template.variables]]}
    componentes = [corpo]
    try:
        if caminho_imagem:
            with open(caminho_imagem, "rb") as f:
                conteudo = f.read()
            mime = "image/png" if caminho_imagem.endswith(".png") else "image/jpeg"
            handle = await client.subir_arquivo_template(os.path.basename(caminho_imagem), conteudo, mime)
            componentes.insert(0, {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [handle]}})
        result = await client.create_template(
            template.waba_id,
            {
                "name": template.meta_template_name,
                "language": template.language,
                "category": template.category,
                "components": componentes,
            },
        )
    except MetaAPIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    template.meta_template_id = result.get("id")
    template.status = _map_meta_status(result.get("status") or "PENDING")
    template.meta_status_raw = result.get("status") or "PENDING"
    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/refresh-status", response_model=schemas.TemplateOut)
async def refresh_template_status(
    template_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    template = _with_variables(db.query(models.Template)).filter(
        models.Template.id == template_id
    ).first()
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
    if not template.meta_template_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Template ainda não foi submetido à Meta"
        )
    waba_id = template.waba_id
    if not waba_id:
        first_num = (
            db.query(models.WhatsappNumber)
            .filter(models.WhatsappNumber.active.is_(True))
            .first()
        )
        waba_id = first_num.waba_id if first_num else None
    if not waba_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "WABA não identificada para este template"
        )

    try:
        token = token_da_waba(db, waba_id)
    except MetaTokenConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    client = MetaClient(access_token=token)
    try:
        remote = await client.get_template_status(template.meta_template_id)
    except MetaAPIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    template.status = _map_meta_status(remote.get("status"))
    template.meta_status_raw = remote.get("status")
    db.commit()
    db.refresh(template)
    return template


def _base_publica(request: Request) -> str | None:
    """Endereço por onde o navegador chegou ao backend, para a imagem ter um
    link que o Chatwoot consiga baixar. Endereço local não serve de link."""
    if settings.public_base_url:
        return None  # dispatch_service.link_publico_imagem monta o link com ele
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    nome = host.rsplit(":", 1)[0] if not host.startswith("[") else host
    if not host or nome in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "backend") or "." not in nome:
        return None
    return f"{proto}://{host}"


def _template_de_imagem(db: Session, template_id: str) -> models.Template:
    template = _with_variables(db.query(models.Template)).filter(
        models.Template.id == template_id
    ).first()
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
    if template.header_type != models.TemplateHeaderType.image:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Este template não tem cabeçalho de imagem habilitado — a opção de mídia só existe para templates com cabeçalho de imagem na Meta",
        )
    return template


def _pasta_pendentes() -> str:
    pasta = os.path.join(settings.media_dir, _PASTA_PENDENTES)
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _limpar_pendentes_vencidas() -> None:
    pasta = _pasta_pendentes()
    limite = time.time() - _VALIDADE_PENDENTE_SEGUNDOS
    for nome in os.listdir(pasta):
        caminho = os.path.join(pasta, nome)
        try:
            if os.path.getmtime(caminho) < limite:
                os.remove(caminho)
        except FileNotFoundError:
            pass


def _caminho_pendente(template_id: str, token: str) -> str:
    achado = _TOKEN_PENDENTE.match(token or "")
    if not achado or achado.group("template") != template_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Imagem otimizada inválida para este template")
    caminho = os.path.join(_pasta_pendentes(), token)
    if not os.path.isfile(caminho):
        raise HTTPException(
            status.HTTP_410_GONE, "A imagem otimizada expirou ou já foi usada — suba a imagem de novo"
        )
    return caminho


def _gravar_imagem_do_template(template: models.Template, conteudo: bytes, ext: str, request: Request) -> None:
    os.makedirs(settings.media_dir, exist_ok=True)
    stored_name = f"{template.id}{ext}"
    # Troca de formato (ex.: .png → .jpg depois da compressão): não deixa o arquivo antigo para trás
    for antiga in (".jpg", ".jpeg", ".png"):
        if antiga != ext:
            try:
                os.remove(os.path.join(settings.media_dir, f"{template.id}{antiga}"))
            except FileNotFoundError:
                pass
    with open(os.path.join(settings.media_dir, stored_name), "wb") as f:
        f.write(conteudo)
    base = _base_publica(request)
    # ?v= muda a cada subida: o arquivo tem sempre o mesmo nome e navegador/Chatwoot guardariam a imagem antiga
    template.image_url = f"{base or ''}/media/{stored_name}?v={uuid.uuid4().hex[:8]}"


@router.post("/{template_id}/image", response_model=schemas.TemplateImagemOut)
async def upload_template_image(
    template_id: str,
    file: UploadFile,
    request: Request,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Imagem que cabe no limite da Meta vai direto para o template. Se
    precisar comprimir, a versão otimizada fica pendente e volta em
    `pendente` para o usuário ver e aprovar (`/image/confirmar`) ou
    descartar (`DELETE /image/pendente`)."""

    template = _template_de_imagem(db, template_id)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _EXTENSOES_IMAGEM_PERMITIDAS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Formato de imagem não suportado — envie .jpg, .png ou .webp",
        )

    content = await file.read(imagem.LIMITE_ENTRADA_BYTES + 1)
    try:
        # Compressão pesa na CPU: fora do event loop, que também atende o worker de disparo
        otimizada = await run_in_threadpool(imagem.otimizar, content)
    except imagem.ImagemInvalida as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if not otimizada.comprimida:
        _gravar_imagem_do_template(template, otimizada.conteudo, otimizada.extensao, request)
        db.commit()
        db.refresh(template)
        return schemas.TemplateImagemOut(template=template)

    _limpar_pendentes_vencidas()
    token = f"{template.id}-{uuid.uuid4().hex}{otimizada.extensao}"
    with open(os.path.join(_pasta_pendentes(), token), "wb") as f:
        f.write(otimizada.conteudo)
    return schemas.TemplateImagemOut(
        template=template,
        pendente=schemas.ImagemPendenteOut(
            token=token,
            url_previa=f"/media/{_PASTA_PENDENTES}/{token}",
            tamanho_original=otimizada.tamanho_original,
            tamanho_final=len(otimizada.conteudo),
            largura_original=otimizada.largura_original,
            altura_original=otimizada.altura_original,
            largura=otimizada.largura,
            altura=otimizada.altura,
            formato_original=otimizada.formato_original,
            formato_final="JPEG" if otimizada.extensao == ".jpg" else "PNG",
            qualidade=otimizada.qualidade,
        ),
    )


@router.post("/{template_id}/image/confirmar", response_model=schemas.TemplateOut)
def confirmar_imagem_otimizada(
    template_id: str,
    payload: schemas.ConfirmarImagemIn,
    request: Request,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    template = _template_de_imagem(db, template_id)
    caminho = _caminho_pendente(template.id, payload.token)
    with open(caminho, "rb") as f:
        conteudo = f.read()
    _gravar_imagem_do_template(template, conteudo, os.path.splitext(caminho)[1], request)
    db.commit()
    os.remove(caminho)
    db.refresh(template)
    return template


@router.delete("/{template_id}/image/pendente", status_code=status.HTTP_204_NO_CONTENT)
def descartar_imagem_otimizada(
    template_id: str,
    token: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    template = _template_de_imagem(db, template_id)
    try:
        os.remove(_caminho_pendente(template.id, token))
    except HTTPException as exc:
        if exc.status_code != status.HTTP_410_GONE:
            raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{template_id}/image", response_model=schemas.TemplateOut)
def remover_imagem_do_template(
    template_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Remove a imagem atribuída ao template, excluindo o arquivo em disco se existir
    e limpando o campo image_url."""
    template = db.get(models.Template, template_id)
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")

    if template.image_url:
        caminho = arquivo_imagem(template)
        if caminho and os.path.isfile(caminho):
            try:
                os.remove(caminho)
            except OSError:
                pass
        template.image_url = None
        db.commit()
        db.refresh(template)

    return template


@router.post("/{template_id}/testar-envio", response_model=schemas.ChatwootTestResult)
@router.post("/{template_id}/testar-envio-chatwoot", response_model=schemas.ChatwootTestResult)
async def testar_envio_template(
    template_id: str,
    payload: schemas.TestarEnvioChatwootIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Dispara agora o template pra um celular específico com os valores de variáveis
    informados — totalmente fora da fila normal, sem gravar em cobranca_fila nem
    contar nos enviados do dia, servindo para validar o envio e as variáveis antes de ligar
    uma faixa nele."""

    template = _with_variables(db.query(models.Template)).filter(
        models.Template.id == template_id
    ).first()
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")

    numero = db.get(models.WhatsappNumber, payload.whatsapp_number_id)
    if not numero:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Número não encontrado")

    template_envio = template
    if template.waba_id and numero.waba_id and template.waba_id != numero.waba_id:
        template_correto = (
            db.query(models.Template)
            .filter(
                models.Template.waba_id == numero.waba_id,
                models.Template.meta_template_name == template.meta_template_name,
                models.Template.status == models.TemplateStatus.approved,
            )
            .first()
        )
        if template_correto:
            template_envio = _with_variables(db.query(models.Template)).filter(models.Template.id == template_correto.id).first()
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"O número {numero.display_phone_number} pertence à WABA {numero.waba_id}, mas o template '{template.name}' pertence à WABA {template.waba_id}. Selecione um número da mesma WABA.",
            )

    celular = normalize_phone(payload.celular)
    if not is_valid_phone(payload.celular):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Celular de destino inválido")

    body_params, header_image_link = montar_parametros_envio(template_envio, payload.variables)

    # 1. Envio via Chatwoot (se o número estiver configurado para Chatwoot)
    if numero.chatwoot_inbox_id:
        try:
            client = chatwoot_client.cliente_configurado(db)
        except chatwoot_client.ChatwootConfigError as exc:
            return schemas.ChatwootTestResult(ok=False, detalhe=str(exc))

        try:
            contact_id, source_id = await client.buscar_ou_criar_contato(
                numero.chatwoot_inbox_id, celular, "Teste de envio"
            )
            conversation_id = await client.buscar_ou_criar_conversa(numero.chatwoot_inbox_id, contact_id, source_id)
            msg = await client.enviar_mensagem_template(
                conversation_id,
                template_envio.body_text,
                template_name=template_envio.meta_template_name,
                category=template_envio.category,
                language=template_envio.language,
                body_params=body_params,
                header_image_url=header_image_link,
            )
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            if msg_id:
                # Espera breve para verificar se a Meta aceitou ou rejeitou de imediato (ex: erro #132001)
                for _ in range(3):
                    await asyncio.sleep(1)
                    status_msg, erro_ext = await client.buscar_status_mensagem(conversation_id, msg_id)
                    if status_msg == "failed":
                        motivo_pt = descrever_erro_envio(erro_ext or "Mensagem recusada")
                        return schemas.ChatwootTestResult(
                            ok=False,
                            detalhe=f"Erro retornado pelo WhatsApp via Chatwoot: {motivo_pt}",
                        )
                    if status_msg in ("delivered", "read"):
                        break
            return schemas.ChatwootTestResult(ok=True, detalhe=f"Mensagem de teste enviada para {celular} via Chatwoot")
        except chatwoot_client.ChatwootAPIError as exc:
            motivo_pt = descrever_erro_envio(f"{exc.status_code}: {exc.payload}")
            return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro retornado pelo Chatwoot: {motivo_pt}")
        except Exception as exc:  # noqa: BLE001
            motivo_pt = descrever_erro_envio(str(exc))
            return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro ao enviar: {motivo_pt}")

    # 2. Envio direto via Meta Cloud API
    try:
        token = token_do_numero(db, numero)
    except MetaTokenConfigError as exc:
        return schemas.ChatwootTestResult(ok=False, detalhe=str(exc))

    meta_client = MetaClient(access_token=token)
    header_image_id = None
    if template_envio.header_type == models.TemplateHeaderType.image:
        caminho_imagem = arquivo_imagem(template_envio)
        if caminho_imagem:
            try:
                header_image_id = await media_id_da_imagem(meta_client, numero.phone_number_id, caminho_imagem)
            except Exception as exc:  # noqa: BLE001
                return schemas.ChatwootTestResult(ok=False, detalhe=f"Falha ao subir imagem do template para a Meta: {exc}")
        elif not header_image_link:
            return schemas.ChatwootTestResult(ok=False, detalhe="Template exige cabeçalho de imagem, mas nenhuma imagem foi cadastrada")

    try:
        await meta_client.send_template_message(
            phone_number_id=numero.phone_number_id,
            to=celular,
            template_name=template_envio.meta_template_name,
            language_code=template_envio.language,
            body_params=body_params,
            header_image_link=header_image_link,
            header_image_id=header_image_id,
        )
        return schemas.ChatwootTestResult(ok=True, detalhe=f"Mensagem de teste enviada para {celular} via Meta")
    except MetaAPIError as exc:
        motivo_pt = descrever_erro_envio(str(exc))
        return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro retornado pela Meta: {motivo_pt}")
    except Exception as exc:  # noqa: BLE001
        motivo_pt = descrever_erro_envio(str(exc))
        return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro ao enviar via Meta: {motivo_pt}")
