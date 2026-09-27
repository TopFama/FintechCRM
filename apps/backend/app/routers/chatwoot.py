import hashlib
import hmac
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import chatwoot_client, crypto, models, schemas
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..dispatch_service import desmarcar_lead_cobrado
from ..utils.erros import descrever_erro_envio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatwoot", tags=["chatwoot"])


def _base_publica_webhook(request: Request) -> str:
    """Resolve a URL base pública deste backend para cadastrar no webhook do Chatwoot."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    if host and not any(h in host for h in ("localhost", "127.0.0.1", "0.0.0.0", "backend")):
        return f"{proto}://{host}"
    return str(request.base_url).rstrip("/")


@router.get("/status", response_model=schemas.ChatwootStatusOut)
def status_chatwoot(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    config = db.query(models.ConfiguracaoChatwoot).first()
    if not config:
        return schemas.ChatwootStatusOut(configurado=False)
    return schemas.ChatwootStatusOut(configurado=True, base_url=config.base_url, account_id=config.account_id)


@router.put("/config", response_model=schemas.ChatwootStatusOut)
def salvar_config(
    payload: schemas.ChatwootConfigIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    config = db.query(models.ConfiguracaoChatwoot).first()
    if not config:
        if not payload.api_access_token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe o token de acesso da API")
        config = models.ConfiguracaoChatwoot(
            base_url=payload.base_url,
            account_id=payload.account_id,
            api_access_token_cifrado=crypto.cifrar(payload.api_access_token),
        )
        db.add(config)
    else:
        # O token guardado só vai para o endereço em que foi cadastrado: trocar o
        # endereço sem informar o token de novo o mandaria para outro servidor.
        if payload.base_url != config.base_url and not payload.api_access_token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ao trocar o endereço, informe o token de acesso de novo")
        config.base_url = payload.base_url
        config.account_id = payload.account_id
        if payload.api_access_token:
            config.api_access_token_cifrado = crypto.cifrar(payload.api_access_token)
    db.commit()
    return schemas.ChatwootStatusOut(configurado=True, base_url=config.base_url, account_id=config.account_id)


@router.post("/testar", response_model=schemas.ChatwootTestResult)
async def testar_conexao(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    try:
        client = chatwoot_client.cliente_configurado(db)
    except chatwoot_client.ChatwootConfigError as exc:
        return schemas.ChatwootTestResult(ok=False, detalhe=str(exc))

    try:
        await client.test_connection()
        return schemas.ChatwootTestResult(ok=True, detalhe="Conexão com o Chatwoot bem-sucedida")
    except chatwoot_client.ChatwootAPIError as exc:
        return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro retornado pelo Chatwoot ({exc.status_code})")
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/config vira mensagem pro usuário
        return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro de conexão com o Chatwoot: {exc}")


@router.post("/sincronizar-webhook", response_model=schemas.ChatwootTestResult)
async def sincronizar_webhook(
    request: Request,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Garante que o webhook do Chatwoot esteja registrado apontando para este backend."""
    try:
        client = chatwoot_client.cliente_configurado(db)
    except chatwoot_client.ChatwootConfigError as exc:
        return schemas.ChatwootTestResult(ok=False, detalhe=str(exc))

    url_webhook = f"{_base_publica_webhook(request)}/chatwoot/webhook"
    try:
        webhook = await client.garantir_webhook(url_webhook)
        return schemas.ChatwootTestResult(
            ok=True,
            detalhe=f"Webhook registrado com sucesso: {webhook.get('url', url_webhook)} (id: {webhook.get('id')})",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao registrar webhook no Chatwoot")
        return schemas.ChatwootTestResult(ok=False, detalhe=f"Falha ao registrar webhook: {exc}")


@router.post("/webhook")
async def webhook_chatwoot(
    request: Request,
    db: Session = Depends(get_db),
):
    """Endpoint receptor de eventos do Chatwoot (message_updated e message_created).
    Recebe atualizações de status da mensagem e, em caso de erro da Meta/WhatsApp,
    atualiza o item da fila correspondente e registra no log de erros."""
    raw_body = await request.body()

    # Validação opcional de assinatura caso CHATWOOT_WEBHOOK_SECRET esteja configurado
    if settings.chatwoot_webhook_secret:
        signature = request.headers.get("X-Chatwoot-Signature", "")
        timestamp = request.headers.get("X-Chatwoot-Timestamp", "")
        if not signature or not timestamp:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura do webhook ausente")
        expected = "sha256=" + hmac.new(
            settings.chatwoot_webhook_secret.encode(),
            f"{timestamp}.{raw_body.decode('utf-8', errors='replace')}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura do webhook inválida")

    try:
        payload = json.loads(raw_body)
    except Exception:
        return {"status": "ignored", "reason": "invalid_json"}

    event = payload.get("event")
    if event not in ("message_created", "message_updated"):
        return {"status": "ok", "action": "ignored_event"}

    msg_id = payload.get("id")
    if not msg_id:
        return {"status": "ok", "action": "missing_id"}

    msg_status = payload.get("status")
    content_attributes = payload.get("content_attributes") or {}
    external_error = content_attributes.get("external_error")

    # Só processamos se o status for failed ou se houver erro externo registrado
    if msg_status != "failed" and not external_error:
        return {"status": "ok", "action": "status_not_failed"}

    item = (
        db.query(models.QueueItem)
        .filter(
            models.QueueItem.whatsapp_message_id == str(msg_id),
            models.QueueItem.status == models.QueueStatus.sent,
        )
        .first()
    )
    if not item:
        return {"status": "ok", "action": "item_not_found"}

    motivo = descrever_erro_envio(external_error or msg_status or "Falha no envio via Chatwoot")
    item.status = models.QueueStatus.error
    item.error_message = f"Chatwoot: {motivo}"
    item.sent_at = None

    desmarcar_lead_cobrado(db, item)

    db.add(
        models.ErrorLog(
            faixa_id=item.faixa_id,
            queue_item_id=item.id,
            message=item.error_message,
        )
    )
    db.commit()
    logger.warning("Mensagem %s (item %s) falhou no Chatwoot: %s", msg_id, item.id, motivo)
    return {"status": "ok", "action": "marked_error", "item_id": item.id}
