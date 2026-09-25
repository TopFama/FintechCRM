import calendar
import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, true
from sqlalchemy.orm import Session

from .. import models, schemas
from .. import cache, pausas, seta_client
from ..services import custo_whatsapp, pagos_janela_service
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


# A tela do Dashboard se atualiza sozinha (auto=true). Várias abas abertas no
# mesmo período fazem uma consulta só a cada TTL; abrir a tela, trocar o
# período ou clicar em "Atualizar agora" sempre recalcula.
RESUMO_TTL_SEGUNDOS = 15
ORCAMENTO_TTL_SEGUNDOS = 600


@router.get("/summary", response_model=schemas.DashboardSummary)
def summary(
    de: date | None = Query(None),
    ate: date | None = Query(None),
    auto: bool = Query(False),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    def calcular():
        return _resumo(db, de, ate).model_dump(mode="json")

    try:
        dados = cache.obter_ou_calcular(
            cache.chave("dashboard-resumo", {"de": de, "ate": ate}), calcular, RESUMO_TTL_SEGUNDOS, reaproveitar=auto
        )
    except cache.CacheIndisponivel:
        dados = calcular()
    return schemas.DashboardSummary(**dados)


def _resumo(db: Session, de: date | None, ate: date | None) -> schemas.DashboardSummary:
    """Cards e tabela por faixa respeitam o período: enviado conta pela data
    do envio, o resto pela data em que entrou na fila."""

    ini, fim = _limites_utc(de, ate)
    periodo = or_(
        and_(models.QueueItem.status == models.QueueStatus.sent, _no_periodo(models.QueueItem.sent_at, ini, fim)),
        and_(models.QueueItem.status != models.QueueStatus.sent, _no_periodo(models.QueueItem.created_at, ini, fim)),
    )

    def count(*status_values: models.QueueStatus) -> int:
        return (
            db.query(func.count(models.QueueItem.id))
            .filter(models.QueueItem.status.in_(status_values), periodo)
            .scalar()
            or 0
        )

    # Envio de campanha/remarketing conta na faixa de atraso do cliente
    # (QueueItem.faixa_atraso), não na faixa própria da campanha.
    por_faixa_rows = (
        db.query(
            models.Faixa.id, models.Faixa.name, models.QueueItem.faixa_atraso, models.QueueItem.status,
            func.count(models.QueueItem.id),
        )
        # Só faixas com movimento no período (sem listar faixa zerada ou excluída)
        .join(models.QueueItem, and_(models.QueueItem.faixa_id == models.Faixa.id, periodo))
        .group_by(models.Faixa.id, models.Faixa.name, models.QueueItem.faixa_atraso, models.QueueItem.status)
        .all()
    )
    id_por_nome = {
        nome: fid
        for fid, nome in db.query(models.Faixa.id, models.Faixa.name).filter(
            models.Faixa.name.in_({r[2] for r in por_faixa_rows if r[2]})
        )
    }
    por_faixa: dict[str, dict] = {}
    for faixa_id, faixa_name, faixa_atraso, status_value, total in por_faixa_rows:
        nome = faixa_atraso or faixa_name
        entry = por_faixa.setdefault(
            nome, {"faixa": nome, "faixa_id": id_por_nome.get(faixa_atraso, faixa_id) if faixa_atraso else faixa_id}
        )
        # reservado = pendente que um envio já pegou; pro operador é pendente
        chave = "pending" if status_value == models.QueueStatus.reserved else status_value.value
        entry[chave] = entry.get(chave, 0) + total

    # Mesma fonte do card "Erros de envio" (itens da fila com erro no período).
    # log_erros só é gravado no disparo; erro de upload, da extração automática
    # e de "já cobrado hoje" não passa por lá, e o card mostrava erro com a lista vazia.
    ultimo_log = (
        db.query(models.ErrorLog.queue_item_id, func.max(models.ErrorLog.created_at).label("quando"))
        .group_by(models.ErrorLog.queue_item_id)
        .subquery()
    )
    quando = func.coalesce(ultimo_log.c.quando, models.QueueItem.created_at)
    erros = (
        db.query(models.QueueItem, models.Faixa.name, quando)
        .join(models.Faixa, models.Faixa.id == models.QueueItem.faixa_id)
        .outerjoin(ultimo_log, ultimo_log.c.queue_item_id == models.QueueItem.id)
        .filter(models.QueueItem.status == models.QueueStatus.error, periodo)
        .order_by(quando.desc())
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
        total_pendentes=count(models.QueueStatus.pending, models.QueueStatus.reserved),
        total_pausados=(
            db.query(func.count(models.QueueItem.id))
            .filter(models.QueueItem.status.in_(pausas.STATUS_PENDENTE), periodo, pausas.Retencao.carregar(db).condicao())
            .scalar()
            or 0
        ),
        total_enviados=count(models.QueueStatus.sent),
        total_erros=count(models.QueueStatus.error),
        total_telefones_invalidos=total_invalidos,
        por_faixa=list(por_faixa.values()),
        erros_recentes=[
            {
                "id": item.id,
                "faixa_id": item.faixa_id,
                "faixa": nome_faixa,
                "cliente": f"{item.codigo_cliente} · {item.nome}" if item.nome else item.codigo_cliente,
                "message": item.error_message or "Erro sem detalhe",
                "created_at": momento.isoformat(),
            }
            for item, nome_faixa, momento in erros
        ],
    )


@router.get("/orcamento-progressao", response_model=schemas.OrcamentoProgressaoOut)
def orcamento_progressao(
    ano: int | None = Query(None, ge=2000, le=2100),
    mes: int | None = Query(None, ge=1, le=12),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    auto: bool = Query(False),
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

    def calcular():
        return _orcamento(db, inicio, fim).model_dump(mode="json")

    try:
        dados = cache.obter_ou_calcular(
            cache.chave("dashboard-orcamento", {"de": inicio, "ate": fim}),
            calcular,
            ORCAMENTO_TTL_SEGUNDOS,
            reaproveitar=auto,
            # Meta fora do ar ou sem permissão numa WABA: não segura o aviso por 10 min
            guardar_se=lambda d: d["valor_gasto_brl"] is not None and not d["avisos"],
        )
    except cache.CacheIndisponivel:
        dados = calcular()
    return schemas.OrcamentoProgressaoOut(**dados)


def _orcamento(db: Session, inicio: date, fim: date) -> schemas.OrcamentoProgressaoOut:
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

    custo = custo_whatsapp.custo_detalhado(db, inicio, fim)
    por_dia, motivo = custo.por_dia, custo.motivo
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
        avisos=[schemas.AvisoCustoWabaOut(waba_id=a.waba_id, numeros=a.numeros, motivo=a.motivo) for a in custo.avisos],
        gasto_por_numero=[
            schemas.GastoNumeroOut(
                numero=n, gasto_brl=v.quantize(Decimal("0.01")), qtd_mensagens=custo.mensagens_por_numero.get(n, 0)
            )
            for n, v in sorted(custo.por_numero.items(), key=lambda kv: -kv[1])
        ],
    )


@router.get("/pagos-7-dias", response_model=schemas.PagosJanelaOut)
def pagos_7_dias(
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Clientes cobrados no período que pagaram em até 7 dias corridos da
    cobrança (regra da Tarefa 5). Cache curto igual ao relatório Quem pagou."""

    def calcular():
        return pagos_janela_service.resumo(db, de, ate, dias_janela=7)

    try:
        try:
            dados = cache.obter_ou_calcular(
                cache.chave("dashboard-pagos-7-dias", {"de": de, "ate": ate}), calcular, ttl_segundos=300
            )
        except cache.CacheIndisponivel:
            dados = calcular()
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SETA indisponível") from exc
    return schemas.PagosJanelaOut(**dados)
