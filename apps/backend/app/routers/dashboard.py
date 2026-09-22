import asyncio
import calendar
import logging
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import cambio, meta_client, models, schemas
from ..database import get_db
from ..deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=schemas.DashboardSummary)
def summary(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    def count(status_value: models.QueueStatus) -> int:
        return (
            db.query(func.count(models.QueueItem.id))
            .filter(models.QueueItem.status == status_value)
            .scalar()
            or 0
        )

    por_faixa_rows = (
        db.query(models.Faixa.name, models.QueueItem.status, func.count(models.QueueItem.id))
        .join(models.QueueItem, models.QueueItem.faixa_id == models.Faixa.id, isouter=True)
        .group_by(models.Faixa.name, models.QueueItem.status)
        .all()
    )
    por_faixa: dict[str, dict] = {}
    for faixa_name, status_value, total in por_faixa_rows:
        entry = por_faixa.setdefault(faixa_name, {"faixa": faixa_name})
        entry[status_value.value if status_value else "sem_envios"] = total

    erros = (
        db.query(models.ErrorLog)
        .order_by(models.ErrorLog.created_at.desc())
        .limit(20)
        .all()
    )

    total_invalidos = db.query(func.count(models.InvalidPhoneRecord.id)).scalar() or 0

    return schemas.DashboardSummary(
        total_pendentes=count(models.QueueStatus.pending),
        total_enviados=count(models.QueueStatus.sent),
        total_erros=count(models.QueueStatus.error),
        total_telefones_invalidos=total_invalidos,
        por_faixa=list(por_faixa.values()),
        erros_recentes=[
            {"id": e.id, "faixa_id": e.faixa_id, "message": e.message, "created_at": e.created_at.isoformat()}
            for e in erros
        ],
    )


@router.get("/orcamento-progressao", response_model=schemas.OrcamentoProgressaoOut)
def orcamento_progressao(
    ano: int = Query(default_factory=lambda: date.today().year),
    mes: int = Query(default_factory=lambda: date.today().month, ge=1, le=12),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Linha de progressão do mês (Tarefa 4): gasto real acumulado dia a dia
    com WhatsApp (Meta Pricing Analytics, convertido em BRL) comparado ao
    orçamento cadastrado. Gasto real é best-effort — sem WABA configurada ou
    com a Meta/câmbio fora do ar, volta None em vez de quebrar a tela."""

    if not (2000 <= ano <= 2100):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ano inválido")

    orcamento = (
        db.query(models.OrcamentoMensal)
        .filter(models.OrcamentoMensal.ano == ano, models.OrcamentoMensal.mes == mes)
        .first()
    )
    valor_orcado = orcamento.valor_orcado if orcamento else Decimal("0.00")

    wabas = {
        w for (w,) in db.query(models.WhatsappNumber.waba_id).filter(models.WhatsappNumber.waba_id.isnot(None)).distinct()
    }
    dias: list[schemas.OrcamentoProgressaoDiaOut] = []
    valor_gasto_brl: Decimal | None = None

    if wabas:
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        inicio = date(ano, mes, 1)
        fim = date(ano, mes, ultimo_dia)
        start_unix = int(datetime.combine(inicio, datetime.min.time()).timestamp())
        end_unix = int(datetime.combine(fim, datetime.max.time()).timestamp())

        async def _buscar() -> list[dict]:
            pontos: list[dict] = []
            for waba_id in wabas:
                token = meta_client.token_da_waba(db, waba_id)
                client = meta_client.MetaClient(token)
                pontos.extend(
                    await client.conversation_analytics(
                        waba_id, start_unix=start_unix, end_unix=end_unix, granularity="DAILY"
                    )
                )
            return pontos

        try:
            pontos = asyncio.run(_buscar())
            cotacao = asyncio.run(cambio.cotacao_usd_brl())
            gasto_por_dia: dict[int, Decimal] = {}
            for p in pontos:
                inicio_ponto = p.get("start")
                if inicio_ponto is None:
                    continue
                dia = datetime.utcfromtimestamp(int(inicio_ponto)).day
                custo_usd = Decimal(str(p.get("cost", 0) or 0))
                gasto_por_dia[dia] = gasto_por_dia.get(dia, Decimal("0.00")) + custo_usd * Decimal(str(cotacao))

            acumulado = Decimal("0.00")
            for dia in range(1, ultimo_dia + 1):
                acumulado += gasto_por_dia.get(dia, Decimal("0.00"))
                dias.append(schemas.OrcamentoProgressaoDiaOut(dia=dia, gasto_acumulado_brl=acumulado.quantize(Decimal("0.01"))))
            valor_gasto_brl = acumulado.quantize(Decimal("0.01"))
        except Exception as exc:  # noqa: BLE001 - dado complementar, não pode derrubar o dashboard
            logger.warning("Não foi possível calcular a progressão de gasto: %s", exc)
            dias = []
            valor_gasto_brl = None

    return schemas.OrcamentoProgressaoOut(
        ano=ano, mes=mes, valor_orcado=valor_orcado, valor_gasto_brl=valor_gasto_brl, dias=dias
    )
