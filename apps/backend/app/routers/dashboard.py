import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from .. import cache, consultas_fila, seta_client
from ..services import custo_whatsapp, pagamentos_service, pagos_janela_service
from ..timezone import hoje_br
from ..database import get_db
from ..deps import get_current_user
from ..utils.xlsx import XLSX_MEDIA_TYPE, build_xlsx
from .comum import erros_de_consulta_pesada

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
            cache.chave("dashboard-resumo-v2", {"de": de, "ate": ate}), calcular, RESUMO_TTL_SEGUNDOS, reaproveitar=auto
        )
    except cache.CacheIndisponivel:
        # Sem Redis não há como proteger o SETA: mostra só o que já está copiado, nunca vai ao ERP
        dados = _resumo(db, de, ate, buscar_novos=False).model_dump(mode="json")
    return schemas.DashboardSummary(**dados)


def _nome_faixa():
    """Faixa da linha de "Por faixa": a de atraso do cliente (envio de
    campanha/remarketing), senão a faixa da fila."""
    return func.coalesce(func.nullif(models.QueueItem.faixa_atraso, ""), models.Faixa.name)


def _resumo(db: Session, de: date | None, ate: date | None, buscar_novos: bool = True) -> schemas.DashboardSummary:
    """Cards e tabela por faixa respeitam o período: enviado conta pela data
    do envio, o resto pela data em que entrou na fila. Pagos por faixa vêm da
    cópia local do SETA; a atualização automática não vai ao SETA."""

    ini, fim = consultas_fila.limites_utc(de, ate)
    periodo = consultas_fila.periodo_dos_cards(de, ate)

    def count(*status_values: models.QueueStatus) -> int:
        return consultas_fila.contar(db, periodo, *status_values)

    # Envio de campanha/remarketing conta na faixa de atraso do cliente
    # (QueueItem.faixa_atraso), não na faixa própria da campanha.
    por_faixa_rows = (
        db.query(
            models.Faixa.id, _nome_faixa(), models.QueueItem.faixa_atraso, models.QueueItem.status,
            func.count(models.QueueItem.id),
        )
        # Só faixas com movimento no período (sem listar faixa zerada ou excluída);
        # faixa só com cliente cobrado entra em _somar_cobrados_por_faixa
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
    for faixa_id, nome, faixa_atraso, status_value, total in por_faixa_rows:
        entry = por_faixa.setdefault(
            nome, {"faixa": nome, "faixa_id": id_por_nome.get(faixa_atraso, faixa_id) if faixa_atraso else faixa_id}
        )
        # reservado = pendente que um envio já pegou; pro operador é pendente
        chave = "pending" if status_value == models.QueueStatus.reserved else status_value.value
        entry[chave] = entry.get(chave, 0) + total

    total_por_faixa = {
        **_somar_cobrados_por_faixa(db, de, ate, por_faixa),
        **_somar_pagos_por_faixa(db, de, ate, por_faixa, buscar_novos),
    }

    total_invalidos = (
        db.query(func.count(models.InvalidPhoneRecord.id))
        .filter(consultas_fila.condicao_periodo(models.InvalidPhoneRecord.created_at, ini, fim))
        .scalar()
        or 0
    )

    return schemas.DashboardSummary(
        total_pendentes=count(models.QueueStatus.pending, models.QueueStatus.reserved),
        total_pausados=consultas_fila.contar_pausados(db, periodo),
        total_enviados=count(models.QueueStatus.sent),
        total_erros=count(models.QueueStatus.error),
        total_telefones_invalidos=total_invalidos,
        por_faixa=list(por_faixa.values()),
        total_por_faixa=schemas.DashboardTotalPorFaixa(**total_por_faixa),
    )


def _somar_cobrados_por_faixa(
    db: Session, de: date | None, ate: date | None, por_faixa: dict[str, dict]
) -> dict[str, int]:
    """Clientes distintos cobrados no período (mesma base do "Pagaram após
    cobrança", base da % Conv.) e, só entre eles, as mensagens enviadas no
    período e quantos receberam alguma (base da Frequência). A coluna Enviado
    inteira misturaria mensagens a clientes cobrados antes do período, e o
    lead marcado como cobrado à mão não recebeu mensagem. Devolve os totais
    da tabela com cada cliente uma vez, mesmo cobrado em mais de uma faixa."""

    cobrados = pagamentos_service.clientes_cobrados_por_faixa(db, cobrado_de=de, cobrado_ate=ate)
    # Faixa cadastrada com cliente cobrado no período e sem fila (lead marcado
    # como cobrado à mão) também ganha linha. Faixa de lead que não existe em
    # Faixas fica de fora, como já acontecia com o "Pagaram após cobrança":
    # sem ela não há relatório para onde a linha levar.
    faltando = set(cobrados) - set(por_faixa)
    if faltando:
        for faixa_id, nome in db.query(models.Faixa.id, models.Faixa.name).filter(models.Faixa.name.in_(faltando)):
            por_faixa[nome] = {"faixa": nome, "faixa_id": faixa_id}
    ini, fim = consultas_fila.limites_utc(de, ate)
    nome_faixa = _nome_faixa()
    cliente_cobrado = (
        select(models.Lead.id)
        .where(
            models.Lead.codigo_cliente == models.QueueItem.codigo_cliente,
            models.Lead.faixa == nome_faixa,
            pagamentos_service.condicao_cobrados(de, ate),
        )
        .exists()
    )
    enviados = (
        db.query(nome_faixa, models.QueueItem.codigo_cliente, func.count(models.QueueItem.id))
        .join(models.Faixa, models.QueueItem.faixa_id == models.Faixa.id)
        .filter(
            models.QueueItem.status == models.QueueStatus.sent,
            consultas_fila.condicao_periodo(models.QueueItem.sent_at, ini, fim),
            cliente_cobrado,
        )
        .group_by(nome_faixa, models.QueueItem.codigo_cliente)
        .all()
    )
    for nome, entry in por_faixa.items():
        entry["clientes_cobrados"] = len(cobrados.get(nome, ()))
        entry["enviados_cobrados"] = entry["clientes_com_envio"] = 0
    com_envio: set[str] = set()
    for nome, codigo, mensagens in enviados:
        if nome in por_faixa:
            por_faixa[nome]["enviados_cobrados"] += mensagens
            por_faixa[nome]["clientes_com_envio"] += 1
            com_envio.add(codigo)
    return {
        "clientes_cobrados": len(set().union(*(cobrados.get(nome, set()) for nome in por_faixa))),
        "enviados_cobrados": sum(e["enviados_cobrados"] for e in por_faixa.values()),
        "clientes_com_envio": len(com_envio),
    }


def _somar_pagos_por_faixa(db: Session, de, ate, por_faixa: dict[str, dict], buscar_novos: bool) -> dict:
    """Clientes cobrados no período que pagaram depois da cobrança (qualquer
    data), por faixa: mesma lista do relatório Quem pagou filtrado pela faixa.
    O valor de cada cliente conta uma vez por faixa, e nos totais devolvidos
    (clientes e valor) uma vez só, mesmo cobrado em mais de uma faixa."""

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
    # Uma linha por cliente e data de cobrança: cobrado em dois dias, as duas
    # linhas trazem o mesmo pagamento (o da primeira já inclui o da segunda).
    # Vale o maior valor do cliente, senão o pagamento soma duas vezes.
    por_cliente: dict[str, dict[str, Decimal]] = {}
    total: dict[str, Decimal] = {}
    for l in linhas:
        faixas = [nome for nome in l["faixa"].split(", ") if nome in por_faixa]
        codigo = l["codigo_cliente"]
        if faixas:
            total[codigo] = max(total.get(codigo, Decimal("0")), l["valor_pago"])
        for nome in faixas:
            clientes = por_cliente.setdefault(nome, {})
            clientes[codigo] = max(clientes.get(codigo, Decimal("0")), l["valor_pago"])
    for nome, clientes in por_cliente.items():
        por_faixa[nome]["pagaram"] = len(clientes)
        por_faixa[nome]["valor_pago"] = str(sum(clientes.values(), Decimal("0")).quantize(Decimal("0.01")))
    return {"pagaram": len(total), "valor_pago": sum(total.values(), Decimal("0")).quantize(Decimal("0.01"))}


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
    conteudo = build_xlsx(
        ["Data", "WABA", "Telefone", "Mensagens cobradas", "Valor cobrado (R$)"], linhas, {4: "#,##0.00"}
    )
    return Response(
        content=conteudo,
        media_type=XLSX_MEDIA_TYPE,
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
    cobrança (regra da Tarefa 5). Usa a mesma lista em cache do relatório Quem
    pagou (5 min), então não consulta o SETA de novo para o mesmo período."""

    with erros_de_consulta_pesada():
        dados = pagos_janela_service.resumo(db, de, ate, dias_janela=7)
    return schemas.PagosJanelaOut(**dados)
