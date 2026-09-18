"""Motor de disparo interno — substitui o que antes era feito pelo n8n
(Schedule Trigger + reserva de cliente + rotação de número + envio + retry).

Roda em background dentro do próprio processo do backend (APScheduler),
varrendo periodicamente as faixas com disparo ativo ou marcadas para rodar
agora ("cobrar base específica sob demanda").
"""

import asyncio
import logging
from datetime import datetime, time as dt_time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session, selectinload

from . import models
from .config import settings
from .database import SessionLocal
from .meta_client import MetaAPIError, MetaClient

logger = logging.getLogger("dispatch_worker")

_WEEKDAY_MAP = {  # Python Monday=0 .. Sunday=6  ->  1..7 como usado em schedule_days
    0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "6", 6: "7",
}


def _within_schedule_window(config: models.DispatchConfig, now: datetime) -> bool:
    if _WEEKDAY_MAP[now.weekday()] not in config.schedule_days.split(","):
        return False
    start = dt_time.fromisoformat(config.schedule_start)
    end = dt_time.fromisoformat(config.schedule_end)
    return start <= now.time() <= end


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


async def _send_one(client: MetaClient, faixa: models.Faixa, item: models.QueueItem, db: Session) -> None:
    if not faixa.numbers:
        item.status = models.QueueStatus.error
        item.error_message = "Faixa sem número de envio configurado"
        db.add(models.ErrorLog(faixa_id=faixa.id, queue_item_id=item.id, message=item.error_message))
        return

    number_entry = faixa.numbers[faixa.last_number_index % len(faixa.numbers)]
    faixa.last_number_index = (faixa.last_number_index + 1) % len(faixa.numbers)
    number = number_entry.whatsapp_number

    ordered_variables = sorted(faixa.template.variables, key=lambda v: v.position)
    body_params = [str(item.variables_json.get(v.internal_name, "")) for v in ordered_variables]

    header_image_link = None
    if faixa.template.header_type == models.TemplateHeaderType.image and faixa.template.image_url:
        if faixa.template.image_url.startswith("http"):
            header_image_link = faixa.template.image_url

    try:
        result = await client.send_template_message(
            phone_number_id=number.phone_number_id,
            to=item.celular,
            template_name=faixa.template.meta_template_name,
            language_code=faixa.template.language,
            body_params=body_params,
            header_image_link=header_image_link,
        )
        item.status = models.QueueStatus.sent
        item.sent_at = datetime.utcnow()
        item.whatsapp_number_id = number.id
        messages = result.get("messages") or []
        if messages:
            item.whatsapp_message_id = messages[0].get("id")
    except MetaAPIError as exc:
        item.status = models.QueueStatus.error
        item.error_message = str(exc)
        item.whatsapp_number_id = number.id
        db.add(models.ErrorLog(faixa_id=faixa.id, queue_item_id=item.id, message=str(exc)))
        logger.warning("Falha ao enviar cobrança %s: %s", item.id, exc)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/config não pode travar o item em "reserved"
        item.status = models.QueueStatus.error
        item.error_message = f"Falha inesperada ao enviar: {exc}"
        item.whatsapp_number_id = number.id
        db.add(models.ErrorLog(faixa_id=faixa.id, queue_item_id=item.id, message=item.error_message))
        logger.exception("Falha inesperada ao enviar cobrança %s", item.id)


async def run_dispatch_cycle() -> None:
    db: Session = SessionLocal()
    try:
        configs = (
            db.query(models.DispatchConfig)
            .options(
                selectinload(models.DispatchConfig.faixa).selectinload(models.Faixa.numbers).selectinload(
                    models.FaixaNumber.whatsapp_number
                ),
                selectinload(models.DispatchConfig.faixa).selectinload(models.Faixa.template).selectinload(
                    models.Template.variables
                ),
            )
            .all()
        )
        now = datetime.utcnow()
        client = MetaClient()

        for config in configs:
            if not _due(config, now):
                continue

            faixa = config.faixa
            try:
                pending_items = (
                    db.query(models.QueueItem)
                    .filter(
                        models.QueueItem.faixa_id == faixa.id,
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
                    await _send_one(client, faixa, item, db)
                    db.commit()
            except Exception:  # noqa: BLE001 - uma faixa com problema não pode travar as demais
                db.rollback()
                logger.exception("Falha ao processar disparo da faixa %s", faixa.id)
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
