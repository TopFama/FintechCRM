import calendar
import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, or_, true
from sqlalchemy.orm import Session

from .. import models, schemas
from .. import cache, pausas, seta_client
from ..services import custo_whatsapp, pagamentos_service, pagos_janela_service
from ..timezone import BUSINESS_TZ, hoje_br
from ..database import get_db
from ..deps import get_current_user
from .reports import _XLSX_MEDIA_TYPE, _build_xlsx

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
        return _resumo(db, de, ate, buscar_novos=not auto).model_dump(mode="json")

    try:
        dados = cache.obter_ou_calcular(
            cache.chave("dashboard-resumo", {"de": de, "ate": ate}), calcular, RESUMO_TTL_SEGUNDOS, reaproveitar=auto
        )
    except cache.CacheIndisponivel:
        dados = calcular()
    return schemas.DashboardSummary(**dados)


def _resumo(db: Session, de: date | None, ate: date | None, buscar_novos: bool = True) -> schemas.DashboardSummary:
    """Cards e tabela por faixa respeitam o período: enviado conta pela data
    do envio, o resto pela data em que entrou na fila. Pagos por faixa vêm da
    cópia local do SETA; a atualização automática não vai ao SETA."""

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

    _somar_pagos_por_faixa(db, de, ate, por_faixa, buscar_novos)

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
    )


def _somar_pagos_por_faixa(db: Session, de, ate, por_faixa: dict[str, dict], buscar_novos: bool) -> None:
    """Clientes cobrados no período que pagaram depois da cobrança (qualquer
    data), por faixa: mesma lista do relatório Quem pagou filtrado pela faixa."""

    for entry in por_faixa.values():
        entry["pagaram"] = 0
        entry["valor_pago"] = "0.00"
    try:
        linhas = pagamentos_service.clientes_que_pagaram(
            db, cobrado_de=de, cobrado_ate=ate, buscar_novos=buscar_novos
        )
    except seta_client.SetaIndisponivel:
        # SETA fora com cliente novo sem cópia: mostra o que já está copiado
        linhas = pagamentos_service.clientes_que_pagaram(db, cobrado_de=de, cobrado_ate=ate, buscar_novos=False)
    clientes: dict[str, set[str]] = {}
    valores: dict[str, Decimal] = {}
    for l in linhas:
        for nome in l["faixa"].split(", "):
            if nome in por_faixa:
                clientes.setdefault(nome, set()).add(l["codigo_cliente"])
                valores[nome] = valores.get(nome, Decimal("0")) + l["valor_pago"]
    for nome, codigos in clientes.items():
        por_faixa[nome]["pagaram"] = len(codigos)
        por_faixa[nome]["valor_pago"] = str(valores[nome].quantize(Decimal("0.01")))


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

    inicio, fim = _periodo_orcamento(ano, mes, de, ate)

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


def _periodo_orcamento(ano, mes, de, ate) -> tuple[date, date]:
    if de or ate:
        if not (de and ate) or de > ate:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe data inicial e final válidas")
        return de, ate
    hoje = hoje_br()
    ano, mes = ano or hoje.year, mes or hoje.month
    return date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])


@router.get("/orcamento-progressao/exportar.xlsx")
def exportar_orcamento_por_dia(
    ano: int | None = Query(None, ge=2000, le=2100),
    mes: int | None = Query(None, ge=1, le=12),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Gasto com WhatsApp por dia, WABA e número (mesmo período do card)."""

    inicio, fim = _periodo_orcamento(ano, mes, de, ate)
    custo = custo_whatsapp.custo_detalhado(db, inicio, fim)
    if custo.por_dia is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, custo.motivo or "Custo da Meta indisponível")
    linhas = [
        [dia, waba, telefone or "—", mensagens, float(gasto.quantize(Decimal("0.01")))]
        for (dia, waba, telefone), (gasto, mensagens) in sorted(custo.por_dia_numero.items())
        if gasto or mensagens
    ]
    conteudo = _build_xlsx(
        ["Data", "WABA", "Telefone", "Mensagens cobradas", "Valor cobrado (R$)"], linhas, {4: "#,##0.00"}
    )
    return Response(
        content=conteudo,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="orcamento_por_dia_{inicio}_{fim}.xlsx"'},
    )


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
