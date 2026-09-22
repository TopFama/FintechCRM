"""Motor de disparo interno — substitui o que antes era feito pelo n8n
(Schedule Trigger + reserva de cliente + rotação de número + envio + retry).

Roda em background dentro do próprio processo do backend (APScheduler),
varrendo periodicamente as faixas com disparo ativo ou marcadas para rodar
agora ("cobrar base específica sob demanda").
"""

import asyncio
import logging
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session, selectinload

from . import chatwoot_client, models
from .config import settings
from .database import SessionLocal
from .meta_client import MetaAPIError, MetaClient, MetaTokenConfigError, token_do_numero
from .timezone import BUSINESS_TZ

logger = logging.getLogger("dispatch_worker")

_WEEKDAY_MAP = {  # Python Monday=0 .. Sunday=6  ->  1..7 como usado em schedule_days
    0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "6", 6: "7",
}


def _within_schedule_window(config: models.DispatchConfig, now_utc: datetime) -> bool:
    """`now_utc` é UTC (relógio do servidor); a janela configurada
    (schedule_start/end, dias da semana) é pensada no horário de quem opera
    o sistema (BUSINESS_TIMEZONE), então a comparação precisa ser feita
    depois de converter — comparar direto em UTC faz a janela "fechar" 3h
    mais cedo (ou mais tarde) do horário real de Brasília, deixando cliente
    na fila sem disparar mesmo "dentro do horário configurado"."""

    local_now = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ)
    if _WEEKDAY_MAP[local_now.weekday()] not in config.schedule_days.split(","):
        return False
    start = dt_time.fromisoformat(config.schedule_start)
    end = dt_time.fromisoformat(config.schedule_end)
    return start <= local_now.time() <= end


def _due(config: models.DispatchConfig, now: datetime) -> bool:
    if config.force_run:
        return True
    if not config.active:
        return False
    if not _within_schedule_window(config, now):
        return False
    if config.last_run_at is None:
        return True
    elapsed = (now - config.last_run_at).total_seconds()
    return elapsed >= config.interval_seconds


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


async def _send_one(envio: models.FaixaEnvio, item: models.QueueItem, db: Session) -> None:
    number = envio.whatsapp_number
    template = envio.template
    item.whatsapp_number_id = number.id
    item.reserved_by = envio.id

    body_params, header_image_link = montar_parametros_envio(template, item.variables_json)

    # Número com inbox do Chatwoot vinculada (Configurações) envia por lá;
    # os demais seguem direto pela Graph API da Meta, como sempre.
    if number.chatwoot_inbox_id:
        await _send_via_chatwoot(envio, item, db, number, template, body_params, header_image_link)
    else:
        await _send_via_meta(envio, item, db, number, template, body_params, header_image_link)


async def _send_via_meta(
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


async def _send_via_chatwoot(
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


async def run_dispatch_cycle() -> None:
    """Varre todo FaixaEnvio (par número+template) com disparo devido.
    Envios da mesma faixa disputam a mesma fila (QueueItem.faixa_id): cada
    ciclo reserva o lote de um envio (marca status=reserved e comita) antes
    de processar o próximo envio, então dois envios da mesma faixa nunca
    pegam o mesmo item — sem isso, dois números diferentes poderiam cobrar
    o mesmo cliente na mesma passada."""

    db: Session = SessionLocal()
    try:
        configs = (
            db.query(models.DispatchConfig)
            .join(models.FaixaEnvio)
            .join(models.Faixa)
            .filter(models.Faixa.active.is_(True), models.FaixaEnvio.active.is_(True))
            .options(
                selectinload(models.DispatchConfig.envio).selectinload(models.FaixaEnvio.whatsapp_number).selectinload(
                    models.WhatsappNumber.meta_token
                ),
                selectinload(models.DispatchConfig.envio).selectinload(models.FaixaEnvio.template).selectinload(
                    models.Template.variables
                ),
            )
            .all()
        )
        now = datetime.utcnow()

        for config in configs:
            if not _due(config, now):
                continue

            envio = config.envio
            try:
                pending_items = (
                    db.query(models.QueueItem)
                    .filter(
                        models.QueueItem.faixa_id == envio.faixa_id,
                        models.QueueItem.status == models.QueueStatus.pending,
                    )
                    .order_by(models.QueueItem.created_at.asc())
                    .limit(config.batch_size)
                    .all()
                )

                for item in pending_items:
                    item.status = models.QueueStatus.reserved
                db.commit()

                for item in pending_items:
                    await _send_one(envio, item, db)
                    db.commit()
            except Exception:  # noqa: BLE001 - um envio com problema não pode travar os demais
                db.rollback()
                logger.exception("Falha ao processar disparo do envio %s (faixa %s)", envio.id, envio.faixa_id)
            finally:
                config.last_run_at = now
                config.force_run = False
                db.commit()
    finally:
        db.close()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_dispatch_cycle,
        "interval",
        seconds=settings.dispatch_worker_interval_seconds,
        id="dispatch_cycle",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
