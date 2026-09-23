import calendar
import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, true
from sqlalchemy.orm import Session

from .. import models, schemas
from ..services import custo_whatsapp
from ..timezone import BUSINESS_TZ, hoje_br
from ..database import get_db
from ..deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _limites_utc(de: date | None, ate: date | None) -> tuple[datetime | None, datetime | None]:
    """Datas locais (GMT-3) → limites em UTC naive, como está gravado no banco."""
    ini = datetime.combine(de, time.min, BUSINESS_TZ).astimezone(UTC).replace(tzinfo=None) if de else None
    fim = (
        datetime.combine(ate + timedelta(days=1), time.min, BUSINESS_TZ).astimezone(UTC).replace(tzinfo=None)
        if ate
        else None
    )
    return ini, fim


def _no_periodo(coluna, ini: datetime | None, fim: datetime | None):
    conds = []
    if ini:
        conds.append(coluna >= ini)
    if fim:
        conds.append(coluna < fim)
    return and_(true(), *conds)


@router.get("/summary", response_model=schemas.DashboardSummary)
def summary(
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Cards e tabela por faixa respeitam o período: enviado conta pela data
    do envio, o resto pela data em que entrou na fila."""

    ini, fim = _limites_utc(de, ate)
    periodo = or_(
        and_(models.QueueItem.status == models.QueueStatus.sent, _no_periodo(models.QueueItem.sent_at, ini, fim)),
        and_(models.QueueItem.status != models.QueueStatus.sent, _no_periodo(models.QueueItem.created_at, ini, fim)),
    )

    def count(status_value: models.QueueStatus) -> int:
        return (
            db.query(func.count(models.QueueItem.id))
            .filter(models.QueueItem.status == status_value, periodo)
            .scalar()
            or 0
        )

    por_faixa_rows = (
        db.query(models.Faixa.name, models.QueueItem.status, func.count(models.QueueItem.id))
        .join(models.QueueItem, and_(models.QueueItem.faixa_id == models.Faixa.id, periodo), isouter=True)
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

    total_invalidos = (
        db.query(func.count(models.InvalidPhoneRecord.id))
        .filter(_no_periodo(models.InvalidPhoneRecord.created_at, ini, fim))
        .scalar()
        or 0
    )

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
    ano: int | None = Query(None, ge=2000, le=2100),
    mes: int | None = Query(None, ge=1, le=12),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Gasto real acumulado com WhatsApp (Meta, em BRL) vs. orçamento. Período
    = um mês (ano/mes, padrão o mês atual) ou personalizado (de/ate); no
    personalizado o orçado soma o orçamento de cada mês tocado."""

    if de or ate:
        if not (de and ate) or de > ate:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe data inicial e final válidas")
        inicio, fim = de, ate
    else:
        hoje = hoje_br()
        ano, mes = ano or hoje.year, mes or hoje.month
        inicio = date(ano, mes, 1)
        fim = date(ano, mes, calendar.monthrange(ano, mes)[1])

    meses = set()
    d = inicio.replace(day=1)
    while d <= fim:
        meses.add((d.year, d.month))
        d = (d + timedelta(days=32)).replace(day=1)
    valor_orcado = sum(
        (
            o.valor_orcado
            for o in db.query(models.OrcamentoMensal)
            if (o.ano, o.mes) in meses
        ),
        Decimal("0.00"),
    )

    por_dia, motivo = custo_whatsapp.gasto_diario_brl(db, inicio, fim)
    dias: list[schemas.OrcamentoProgressaoDiaOut] = []
    valor_gasto_brl: Decimal | None = None
    if por_dia is not None:
        acumulado = Decimal("0.00")
        d = inicio
        while d <= fim:
            acumulado += por_dia.get(d, Decimal("0"))
            dias.append(schemas.OrcamentoProgressaoDiaOut(data=d, gasto_acumulado_brl=acumulado.quantize(Decimal("0.01"))))
            d += timedelta(days=1)
        valor_gasto_brl = acumulado.quantize(Decimal("0.01"))

    return schemas.OrcamentoProgressaoOut(
        de=inicio,
        ate=fim,
        valor_orcado=valor_orcado,
        valor_gasto_brl=valor_gasto_brl,
        motivo_sem_gasto=motivo,
        dias=dias,
    )
