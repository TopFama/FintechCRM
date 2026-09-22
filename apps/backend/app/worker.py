"""Motor de disparo interno — substitui o que antes era feito pelo n8n
(Schedule Trigger + reserva de cliente + rotação de número + envio + retry).

Roda em background dentro do próprio processo do backend (APScheduler),
varrendo periodicamente as faixas com disparo ativo ou marcadas para rodar
agora ("cobrar base específica sob demanda"). Só sabe *quando* rodar e como
reservar os itens da fila — *como* um item é efetivamente enviado é
responsabilidade de dispatch_service.py.
"""

import logging
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session, selectinload

from . import models
from .config import settings
from .database import SessionLocal
from .dispatch_service import enviar_item
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
                    await enviar_item(envio, item, db)
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
