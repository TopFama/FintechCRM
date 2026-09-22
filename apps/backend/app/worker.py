"""Motor de disparo interno — substitui o que antes era feito pelo n8n
(Schedule Trigger + reserva de cliente + rotação de número + envio + retry).

Roda em background dentro do próprio processo do backend (APScheduler),
varrendo periodicamente as faixas com disparo ativo ou marcadas para rodar
agora ("cobrar base específica sob demanda"). Só sabe *quando* rodar e como
reservar os itens da fila — *como* um item é efetivamente enviado é
responsabilidade de dispatch_service.py.
"""

import logging
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session, selectinload

from . import models
from .config import settings
from .database import SessionLocal
from .dispatch_service import enviar_item
from .leads_service import gerar_leads_de_clientes
from .timezone import BUSINESS_TZ

logger = logging.getLogger("dispatch_worker")

_WEEKDAY_MAP = {  # Python Monday=0 .. Sunday=6  ->  1..7 como usado em schedule_days
    0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "6", 6: "7",
}


def _local_now(now_utc: datetime):
    """`now_utc` é UTC (relógio do servidor); a janela configurada
    (schedule_start/end, dias da semana) é pensada no horário de quem opera
    o sistema (BUSINESS_TIMEZONE), então a comparação precisa ser feita
    depois de converter — comparar direto em UTC faz a janela "fechar" 3h
    mais cedo (ou mais tarde) do horário real de Brasília, deixando cliente
    na fila sem disparar mesmo "dentro do horário configurado"."""
    return now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ)


def _within_schedule_window(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> bool:
    local_now = _local_now(now_utc)
    if _WEEKDAY_MAP[local_now.weekday()] not in global_config.schedule_days.split(","):
        return False
    start = dt_time.fromisoformat(global_config.schedule_start)
    end = dt_time.fromisoformat(global_config.schedule_end)
    return start <= local_now.time() <= end


def _due(config: models.DispatchConfig, dentro_da_janela: bool, now: datetime) -> bool:
    if config.force_run:
        return True
    if not config.active:
        return False
    if not dentro_da_janela:
        return False
    if config.last_run_at is None:
        return True
    elapsed = (now - config.last_run_at).total_seconds()
    return elapsed >= config.interval_seconds


def _deve_extrair_leads(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> bool:
    """Extração automática de leads pouco antes do disparo começar (opcional),
    pra reduzir a chance de cobrar quem já pagou mais cedo no mesmo dia. Roda
    no máximo uma vez por dia, na janela [schedule_start - N min, schedule_start)."""

    if not global_config.leads_auto_extract:
        return False
    local_now = _local_now(now_utc)
    if _WEEKDAY_MAP[local_now.weekday()] not in global_config.schedule_days.split(","):
        return False
    if global_config.leads_auto_extract_last_run == local_now.date():
        return False
    inicio_disparo = dt_time.fromisoformat(global_config.schedule_start)
    janela_inicio = (
        datetime.combine(local_now.date(), inicio_disparo) - timedelta(minutes=global_config.leads_auto_extract_minutos_antes)
    ).time()
    return janela_inicio <= local_now.time() < inicio_disparo


def _extrair_leads_automatico(db: Session) -> None:
    """Gera leads da base de cobrança com os mesmos filtros padrão da tela
    (nenhuma faixa/cluster/loja específica, só primeiro dia + regra WhatsApp),
    equivalente a clicar em "Gerar leads" sem nenhum filtro aplicado."""

    from .cobranca_base import buscar_base  # import local: evita ciclo de import com worker

    job = buscar_base(db)
    if job["status"] != "ready":
        logger.info("Extração automática de leads: base de cobrança ainda processando, tenta no próximo ciclo")
        return
    criados, ja_existiam, sem_celular = gerar_leads_de_clientes(db, job["data"], created_by=None)
    logger.info(
        "Extração automática de leads: %s criados, %s já existiam, %s sem celular", criados, ja_existiam, sem_celular
    )


async def run_dispatch_cycle() -> None:
    """Varre todo FaixaEnvio (par número+template) com disparo devido.
    Envios da mesma faixa disputam a mesma fila (QueueItem.faixa_id): cada
    ciclo reserva o lote de um envio (marca status=reserved e comita) antes
    de processar o próximo envio, então dois envios da mesma faixa nunca
    pegam o mesmo item — sem isso, dois números diferentes poderiam cobrar
    o mesmo cliente na mesma passada."""

    db: Session = SessionLocal()
    try:
        global_config = db.query(models.GlobalDispatchConfig).filter(models.GlobalDispatchConfig.id == "global").first()
        if global_config is None:
            global_config = models.GlobalDispatchConfig(id="global")
            db.add(global_config)
            db.commit()
            db.refresh(global_config)

        now = datetime.utcnow()

        if _deve_extrair_leads(global_config, now):
            try:
                _extrair_leads_automatico(db)
            except Exception:  # noqa: BLE001 - falha na extração não pode travar o disparo
                db.rollback()
                logger.exception("Falha na extração automática de leads")
            else:
                global_config.leads_auto_extract_last_run = _local_now(now).date()
                db.commit()

        dentro_da_janela = _within_schedule_window(global_config, now)

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

        for config in configs:
            if not _due(config, dentro_da_janela, now):
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
