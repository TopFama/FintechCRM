"""Envio de uma cobrança individual (monta os parâmetros do template e manda
pela Meta ou pelo Chatwoot, conforme o número). Extraído de worker.py: este
módulo só sabe *como* enviar um item; *quando* rodar o ciclo de disparo é
responsabilidade de worker.py (agendamento)."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from . import chatwoot_client, models
from .meta_client import MetaAPIError, MetaClient, MetaTokenConfigError, token_do_numero

logger = logging.getLogger("dispatch_worker")


def montar_parametros_envio(template: models.Template, variables_json: dict) -> tuple[list[str], str | None]:
    """Body params (na ordem das variáveis do template) e link da imagem de
    cabeçalho, a partir de um dict variavel.internal_name -> valor. Usado no
    disparo de verdade (variables_json de QueueItem) e no teste de envio
    manual (Templates → Testar envio).

    Uma faixa com um único template ativo grava `variables_json` "achatado"
    (internal_name -> valor, formato de sempre). Uma faixa com mais de um
    template ativo (vários pares número+template, ver FaixaEnvio) grava por
    template — `{template_id: {internal_name: valor}}` — já que cada item
    da fila pode acabar sendo enviado por qualquer um dos envios ativos da
    faixa; aqui resolve pra qual formato veio e usa o dict certo."""

    dados = variables_json or {}
    if dados and all(isinstance(v, dict) for v in dados.values()):
        dados = dados.get(template.id, {})

    ordered_variables = sorted(template.variables, key=lambda v: v.position)
    body_params = [str(dados.get(v.internal_name, "")) for v in ordered_variables]

    header_image_link = None
    if template.header_type == models.TemplateHeaderType.image and template.image_url:
        if template.image_url.startswith("http"):
            header_image_link = template.image_url

    return body_params, header_image_link


async def enviar_item(envio: models.FaixaEnvio, item: models.QueueItem, db: Session) -> None:
    number = envio.whatsapp_number
    template = envio.template
    item.whatsapp_number_id = number.id
    item.reserved_by = envio.id

    body_params, header_image_link = montar_parametros_envio(template, item.variables_json)

    # Número com inbox do Chatwoot vinculada (Configurações) envia por lá;
    # os demais seguem direto pela Graph API da Meta, como sempre.
    if number.chatwoot_inbox_id:
        await _enviar_via_chatwoot(envio, item, db, number, template, body_params, header_image_link)
    else:
        await _enviar_via_meta(envio, item, db, number, template, body_params, header_image_link)


def _marcar_lead_cobrado(db: Session, item: models.QueueItem) -> None:
    """Envio real marca o lead como cobrado — é o que alimenta "Leads enviados".
    Envio de campanha marca o lead da campanha (que fica na faixa de atraso do
    cliente); envio da régua, o lead da régua daquela faixa."""
    faixa = db.get(models.Faixa, item.faixa_id)
    if faixa is None:
        return
    if faixa.tipo == models.TIPO_CAMPANHA:
        filtro = [models.Lead.campanha_id == faixa.campanha_id]
    else:
        filtro = [models.Lead.faixa == faixa.name, models.Lead.campanha_id == ""]
    db.query(models.Lead).filter(
        models.Lead.codigo_cliente == item.codigo_cliente,
        *filtro,
        models.Lead.status == "novo",
    ).update({"status": "cobrado", "cobrado_em": item.sent_at}, synchronize_session=False)


async def _enviar_via_meta(
    envio: models.FaixaEnvio,
    item: models.QueueItem,
    db: Session,
    number: models.WhatsappNumber,
    template: models.Template,
    body_params: list[str],
    header_image_link: str | None,
) -> None:
    try:
        token = token_do_numero(db, number)
    except MetaTokenConfigError as exc:
        item.status = models.QueueStatus.error
        item.error_message = str(exc)
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.warning("Falha ao obter token da Meta para envio %s: %s", item.id, exc)
        return

    client = MetaClient(access_token=token)
    try:
        result = await client.send_template_message(
            phone_number_id=number.phone_number_id,
            to=item.celular,
            template_name=template.meta_template_name,
            language_code=template.language,
            body_params=body_params,
            header_image_link=header_image_link,
        )
        item.status = models.QueueStatus.sent
        item.sent_at = datetime.utcnow()
        _marcar_lead_cobrado(db, item)
        messages = result.get("messages") or []
        if messages:
            item.whatsapp_message_id = messages[0].get("id")
    except MetaAPIError as exc:
        item.status = models.QueueStatus.error
        item.error_message = str(exc)
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=str(exc)))
        logger.warning("Falha ao enviar cobrança %s: %s", item.id, exc)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/config não pode travar o item em "reserved"
        item.status = models.QueueStatus.error
        item.error_message = f"Falha inesperada ao enviar: {exc}"
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.exception("Falha inesperada ao enviar cobrança %s", item.id)


async def _enviar_via_chatwoot(
    envio: models.FaixaEnvio,
    item: models.QueueItem,
    db: Session,
    number: models.WhatsappNumber,
    template: models.Template,
    body_params: list[str],
    header_image_link: str | None,
) -> None:
    try:
        client = chatwoot_client.cliente_configurado(db)
    except chatwoot_client.ChatwootConfigError as exc:
        item.status = models.QueueStatus.error
        item.error_message = str(exc)
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.warning("Falha ao obter configuração do Chatwoot para envio %s: %s", item.id, exc)
        return

    try:
        contact_id, source_id = await client.buscar_ou_criar_contato(
            number.chatwoot_inbox_id, item.celular, item.nome
        )
        conversation_id = await client.buscar_ou_criar_conversa(number.chatwoot_inbox_id, contact_id, source_id)
        await client.enviar_mensagem_template(
            conversation_id,
            template.body_text,
            template_name=template.meta_template_name,
            category=template.category,
            language=template.language,
            body_params=body_params,
            header_image_url=header_image_link,
        )
        item.status = models.QueueStatus.sent
        item.sent_at = datetime.utcnow()
        _marcar_lead_cobrado(db, item)
    except chatwoot_client.ChatwootAPIError as exc:
        item.status = models.QueueStatus.error
        item.error_message = str(exc)
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=str(exc)))
        logger.warning("Falha ao enviar cobrança %s via Chatwoot: %s", item.id, exc)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/config não pode travar o item em "reserved"
        item.status = models.QueueStatus.error
        item.error_message = f"Falha inesperada ao enviar via Chatwoot: {exc}"
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.exception("Falha inesperada ao enviar cobrança %s via Chatwoot", item.id)
