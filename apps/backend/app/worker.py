"""Motor de disparo interno — substitui o que antes era feito pelo n8n
(Schedule Trigger + reserva de cliente + rotação de número + envio + retry).

Roda em background dentro do próprio processo do backend (APScheduler),
varrendo periodicamente as faixas com disparo ativo ou marcadas para rodar
agora ("cobrar base específica sob demanda"). Só sabe *quando* rodar e como
reservar os itens da fila — *como* um item é efetivamente enviado é
responsabilidade de dispatch_service.py.
"""

import asyncio
import logging
from datetime import datetime, time as dt_time, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session, selectinload

from . import models, seta_client
from .services import pagamentos_seta
from .pausas import Retencao
from .config import settings
from .database import SessionLocal
from .dispatch_service import enviar_item
from .blacklist import Blacklist
from . import elegibilidade
from .fila_automatica import enfileirar_leads, expirar_nao_enviados
from .leads_service import gerar_leads_de_clientes
from .timezone import para_br

logger = logging.getLogger("dispatch_worker")

_WEEKDAY_MAP = {  # Python Monday=0 .. Sunday=6  ->  1..7 como usado em schedule_days
    0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "6", 6: "7",
}


def _within_schedule_window(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> bool:
    local_now = para_br(now_utc)
    if _WEEKDAY_MAP[local_now.weekday()] not in global_config.schedule_days.split(","):
        return False
    start = dt_time.fromisoformat(global_config.schedule_start)
    end = dt_time.fromisoformat(global_config.schedule_end)
    return start <= local_now.time() <= end


def _due(
    config: models.DispatchConfig, dentro_da_janela: bool, now: datetime, interval_seconds: int
) -> bool:
    if config.force_run:
        return True
    if not config.active:
        return False
    if not dentro_da_janela:
        return False
    if config.last_run_at is None:
        return True
    elapsed = (now - config.last_run_at).total_seconds()
    return elapsed >= interval_seconds


def _deve_extrair_leads(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> bool:
    """Extração automática de leads pouco antes do disparo começar (opcional),
    pra reduzir a chance de cobrar quem já pagou mais cedo no mesmo dia. Roda
    no máximo uma vez por dia, na janela [schedule_start - N min, schedule_start)."""

    if not global_config.leads_auto_extract:
        return False
    local_now = para_br(now_utc)
    if _WEEKDAY_MAP[local_now.weekday()] not in global_config.schedule_days.split(","):
        return False
    if global_config.leads_auto_extract_last_run == local_now.date():
        return False
    inicio_disparo = dt_time.fromisoformat(global_config.schedule_start)
    return _inicio_antecipado(global_config) <= local_now.time() < inicio_disparo


def _inicio_antecipado(global_config: models.GlobalDispatchConfig) -> dt_time:
    """Início do disparo menos os minutos da extração de leads, sem voltar para
    o dia anterior: com início 00:10 e 15 min antes, a conta dava 23:55 e a
    janela 23:55–00:10 nunca era verdadeira. Nesse caso começa à meia-noite."""

    inicio = dt_time.fromisoformat(global_config.schedule_start)
    minutos = inicio.hour * 60 + inicio.minute - global_config.leads_auto_extract_minutos_antes
    return dt_time(*divmod(max(minutos, 0), 60))


def _extrair_leads_automatico(db: Session) -> bool:
    """Gera leads da base de cobrança com os mesmos filtros padrão da tela
    (nenhuma faixa/cluster/loja específica, só primeiro dia + regra WhatsApp),
    equivalente a clicar em "Gerar leads" sem nenhum filtro aplicado."""

    from .cobranca_base import buscar_base  # import local: evita ciclo de import com worker

    job = buscar_base(db)
    if job["status"] != "ready":
        logger.info("Extração automática de leads: base de cobrança ainda processando, tenta no próximo ciclo")
        return False
    criados, ja_existiam, sem_celular = gerar_leads_de_clientes(db, job["data"], created_by=None)
    na_fila = enfileirar_leads(db, job["data"])
    logger.info(
        "Extração automática de leads: %s criados, %s já existiam, %s sem celular, %s na fila de disparo",
        criados, ja_existiam, sem_celular, na_fila,
    )
    return True


def _deve_rodar_remarketing(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> bool:
    """Remarketing do Renegocie: uma vez por dia útil de disparo, a partir do
    mesmo momento da extração de leads (N min antes do início) até o fim da
    janela — se o backend subir no meio do dia, ainda roda naquele dia."""

    if global_config.remarketing_last_run == para_br(now_utc).date():
        return False
    return _na_janela_diaria(global_config, now_utc)


def _na_janela_diaria(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> bool:
    """Dia de disparo, de N min antes do início (extração de leads) até o fim
    da janela: quando rodam remarketing e campanhas."""

    local_now = para_br(now_utc)
    if _WEEKDAY_MAP[local_now.weekday()] not in global_config.schedule_days.split(","):
        return False
    return _inicio_antecipado(global_config) <= local_now.time() < dt_time.fromisoformat(global_config.schedule_end)


# Espera depois de uma falha (SETA, Renegocie) antes de tentar de novo: sem
# isso a rotina era refeita a cada ciclo do worker (5 s) o dia inteiro.
ESPERA_APOS_FALHA = timedelta(minutes=5)
_proxima_tentativa: dict[str, datetime] = {}


def _pode_tentar(chave: str, now: datetime) -> bool:
    return _proxima_tentativa.get(chave, now) <= now


def _falhou(chave: str, now: datetime) -> None:
    _proxima_tentativa[chave] = now + ESPERA_APOS_FALHA
    logger.warning("'%s' falhou; nova tentativa em %s min", chave, int(ESPERA_APOS_FALHA.total_seconds() // 60))


def _ok(chave: str) -> None:
    _proxima_tentativa.pop(chave, None)


def _global_config(db: Session) -> models.GlobalDispatchConfig:
    global_config = db.query(models.GlobalDispatchConfig).filter(models.GlobalDispatchConfig.id == "global").first()
    if global_config is None:
        global_config = models.GlobalDispatchConfig(id="global")
        db.add(global_config)
        db.commit()
        db.refresh(global_config)
    return global_config


def _rotinas_do_dia(now: datetime) -> None:
    """Extração de leads, remarketing, régua de quem recebeu campanha,
    campanhas e expiração da fila. São consultas pesadas e bloqueantes (SETA,
    Renegocie), então rodam numa thread à parte (ver run_dispatch_cycle), com
    sessão própria, sem travar a API enquanto isso."""

    db: Session = SessionLocal()
    try:
        global_config = _global_config(db)

        if _deve_extrair_leads(global_config, now) and _pode_tentar("extracao", now):
            try:
                concluiu = _extrair_leads_automatico(db)
            except Exception:  # noqa: BLE001 - falha na extração não pode travar o disparo
                db.rollback()
                logger.exception("Falha na extração automática de leads")
                _falhou("extracao", now)
            else:
                _ok("extracao")
                # Base ainda calculando (cache frio): não marca o dia como feito,
                # senão a extração nunca roda de verdade.
                if concluiu:
                    global_config.leads_auto_extract_last_run = para_br(now).date()
                    db.commit()

        if _deve_rodar_remarketing(global_config, now) and _pode_tentar("remarketing", now):
            from . import remarketing  # import local: evita ciclo de import com worker

            # Só conta o dia como feito quando algum segmento ligado já tem
            # número + template: ligar antes de atribuir não perde o dia.
            if any(r.ativo and any(e.active for e in r.faixa.envios) for r in remarketing.garantir_segmentos(db)):
                try:
                    remarketing.executar(db)
                except Exception:  # noqa: BLE001 - Renegocie/SETA fora não pode travar o disparo
                    db.rollback()
                    logger.exception("Falha no remarketing do Renegocie")
                    _falhou("remarketing", now)
                else:
                    _ok("remarketing")
                    global_config.remarketing_last_run = para_br(now).date()
                    db.commit()

        if _na_janela_diaria(global_config, now):
            # Campanhas: mesmo horário do remarketing, cada uma uma vez por dia.
            from . import campanhas  # import local: evita ciclo de import com worker

            # Antes das campanhas do dia: quem recebeu campanha em dia anterior
            # entra na régua da faixa de atraso (base calculando = próximo ciclo).
            if _pode_tentar("regua", now):
                try:
                    campanhas.enfileirar_na_regua(db)
                except Exception:  # noqa: BLE001 - SETA fora não pode travar o disparo
                    db.rollback()
                    logger.exception("Falha ao levar à régua quem recebeu campanha")
                    _falhou("regua", now)
                else:
                    _ok("regua")

            for campanha in campanhas.campanhas_para_hoje(db):
                chave = f"campanha:{campanha.id}"
                if not _pode_tentar(chave, now):
                    continue
                try:
                    resultado = campanhas.executar(db, campanha)
                except Exception:  # noqa: BLE001 - SETA fora não pode travar o disparo
                    db.rollback()
                    logger.exception("Falha na campanha '%s'", campanha.nome)
                    _falhou(chave, now)
                    continue
                _ok(chave)
                # Base ainda calculando no SETA: tenta de novo no próximo ciclo.
                if resultado.get("status") == "ready":
                    campanha.ultima_execucao_dia = para_br(now).date()
                    db.commit()

        try:
            expirar_nao_enviados(db, global_config, now)
        except Exception:  # noqa: BLE001 - limpeza não pode travar o disparo
            db.rollback()
            logger.exception("Falha ao expirar a fila após o horário final")
    finally:
        db.close()


async def run_dispatch_cycle() -> None:
    """Varre todo FaixaEnvio (par número+template) com disparo devido.
    Envios da mesma faixa disputam a mesma fila (QueueItem.faixa_id): cada
    ciclo reserva o lote de um envio (marca status=reserved e comita) antes
    de processar o próximo envio, então dois envios da mesma faixa nunca
    pegam o mesmo item — sem isso, dois números diferentes poderiam cobrar
    o mesmo cliente na mesma passada."""

    now = datetime.utcnow()
    # O worker divide o event loop com a API: as rotinas bloqueantes vão para
    # uma thread, e o loop segue atendendo as telas enquanto elas rodam.
    await asyncio.to_thread(_rotinas_do_dia, now)

    db: Session = SessionLocal()
    try:
        global_config = _global_config(db)

        dentro_da_janela = _within_schedule_window(global_config, now)
        # Pausas ativas lidas uma vez por ciclo; conferidas de novo antes de cada envio
        retencao = Retencao.carregar(db)
        blacklist = Blacklist(db)

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
            if not _due(config, dentro_da_janela, now, global_config.interval_seconds):
                continue

            envio = config.envio
            try:
                if envio.faixa_id in retencao.faixas:
                    continue
                pending_items = (
                    db.query(models.QueueItem)
                    .filter(
                        models.QueueItem.faixa_id == envio.faixa_id,
                        models.QueueItem.status == models.QueueStatus.pending,
                        ~retencao.condicao(),
                    )
                    .order_by(models.QueueItem.created_at.asc())
                    .limit(global_config.batch_size)
                    .all()
                )

                for item in pending_items:
                    item.status = models.QueueStatus.reserved
                db.commit()

                for item in pending_items:
                    # Pausa criada ou parada feita depois da reserva: relê o item e as pausas
                    db.refresh(item)
                    if item.status != models.QueueStatus.reserved:
                        continue
                    motivo = elegibilidade.conferir_saida(db, item, blacklist)
                    if motivo == elegibilidade.RETIDO:
                        item.status = models.QueueStatus.pending
                        db.commit()
                        continue
                    if motivo:
                        item.status = models.QueueStatus.error
                        item.error_message = motivo
                        db.commit()
                        continue
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


def sincronizar_pagamentos() -> None:
    """Rodada incremental da cópia local das baixas do SETA (ver
    services/pagamentos_seta.py). Roda no pool de threads do APScheduler.
    Confere a cada minuto, mas só lê o SETA com alguém usando o CRM e no
    máximo uma vez a cada pagamentos_sync_interval_seconds."""
    if not seta_client.is_configured() or not pagamentos_seta.rodada_devida(settings.pagamentos_sync_interval_seconds):
        return
    db = SessionLocal()
    try:
        pagamentos_seta.sincronizar(db)
    except seta_client.SetaIndisponivel as exc:
        logger.warning("Sincronização de pagamentos adiada: %s", exc)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Falha ao sincronizar pagamentos do SETA")
    finally:
        db.close()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        sincronizar_pagamentos,
        "interval",
        seconds=60,
        id="pagamentos_seta",
        max_instances=1,
        coalesce=True,
    )
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
