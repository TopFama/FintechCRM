"""Gasto real com WhatsApp (Meta Pricing Analytics, USD → BRL) por dia, usado
no orçamento do Dashboard e no "valor a pagar" do relatório de efetividade."""

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .. import cambio, meta_client, models
from ..timezone import BUSINESS_TZ

logger = logging.getLogger(__name__)


def gasto_diario_brl(db: Session, inicio: date, fim: date) -> tuple[dict[date, Decimal] | None, str | None]:
    """(gasto por dia em BRL, motivo) — gasto None quando não deu pra calcular
    nada; o motivo explica por quê (vai pra tela, não só pro log)."""

    wabas = {
        w
        for (w,) in db.query(models.WhatsappNumber.waba_id)
        .filter(models.WhatsappNumber.waba_id.isnot(None), models.WhatsappNumber.active.is_(True))
        .distinct()
    }
    if not wabas:
        return None, "Nenhum número de WhatsApp ativo com WABA cadastrado."

    start_unix = int(datetime.combine(inicio, time.min, BUSINESS_TZ).timestamp())
    fim_dt = datetime.combine(fim + timedelta(days=1), time.min, BUSINESS_TZ)
    # A Meta recusa período que termina no futuro
    end_unix = int(min(fim_dt, datetime.now(ZoneInfo("UTC"))).timestamp())
    if end_unix <= start_unix:
        return {}, None

    async def _buscar() -> tuple[list[dict], list[str]]:
        pontos: list[dict] = []
        falhas: list[str] = []
        for waba_id in wabas:
            try:
                token = meta_client.token_da_waba(db, waba_id)
                client = meta_client.MetaClient(token)
                pontos.extend(await client.pricing_analytics(waba_id, start_unix=start_unix, end_unix=end_unix))
            except Exception as exc:  # noqa: BLE001 - uma WABA com problema não zera as outras
                falhas.append(f"WABA {waba_id}: {exc}")
        return pontos, falhas

    try:
        pontos, falhas = asyncio.run(_buscar())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao buscar custo na Meta: %s", exc)
        return None, f"Falha ao consultar a Meta: {exc}"

    if falhas and len(falhas) == len(wabas):
        logger.warning("Custo do WhatsApp indisponível: %s", "; ".join(falhas))
        return None, "; ".join(falhas)

    try:
        cotacao = Decimal(str(asyncio.run(cambio.cotacao_usd_brl())))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Câmbio indisponível: %s", exc)
        return None, f"Cotação do dólar indisponível: {exc}"

    por_dia: dict[date, Decimal] = {}
    for p in pontos:
        if p.get("start") is None:
            continue
        dia = datetime.fromtimestamp(int(p["start"]), BUSINESS_TZ).date()
        custo = Decimal(str(p.get("cost", 0) or 0)) * cotacao
        por_dia[dia] = por_dia.get(dia, Decimal("0")) + custo
    return por_dia, ("; ".join(falhas) if falhas else None)
