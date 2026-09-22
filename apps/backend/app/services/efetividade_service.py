"""Regras do relatório de efetividade da cobrança (Tarefas 5 e 6): junta as
parcelas cobradas com a situação delas no SETA e com o custo real do
WhatsApp na Meta. Extraído de routers/reports.py — os endpoints HTTP ficam
finos, só validam parâmetros e devolvem o que este módulo calcula.

As duas funções ainda levantam HTTPException diretamente (SETA/Google fora
do ar), o que amarra esta "camada de serviço" ao FastAPI — um acoplamento
que ficou de fora do escopo desta primeira extração; o `raise` aqui é
convertido pelo próprio FastAPI na resposta HTTP igual seria se estivesse
no router, então não muda comportamento nenhum, só a localização do código."""

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import cambio, google_client, lojas as lojas_base, meta_client, models, seta_client
from ..regras_db import carregar_regras
from ..relatorio_efetividade import montar_relatorio

logger = logging.getLogger(__name__)


def obter_dados_efetividade(
    db: Session,
    *,
    cobrado_de: date | None = None,
    cobrado_ate: date | None = None,
    dias_janela: int | None = None,
    faixa: list[str] | None = None,
    cluster: list[str] | None = None,
    loja: list[str] | None = None,
    regional: list[str] | None = None,
    estado: list[str] | None = None,
    cluster_inad: list[str] | None = None,
) -> tuple[dict, int, list[dict]]:
    try:
        codigos_loja = lojas_base.combinar_lojas(
            db,
            loja=loja,
            regional=regional,
            estado=estado,
            cluster_inad=cluster_inad,
        )
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    regras = carregar_regras(db)
    if codigos_loja is not None and len(codigos_loja) == 0:
        return montar_relatorio([], lojas_info={}, faixas_ordem=regras.nomes_faixa), 0, []

    try:
        lojas_info = {l["filial"]: l for l in lojas_base.listar_lojas(db)}
    except google_client.GoogleIndisponivel:
        lojas_info = {}

    leads_query = db.query(models.Lead).filter(models.Lead.status == "cobrado")
    if cobrado_de:
        leads_query = leads_query.filter(
            models.Lead.cobrado_em >= datetime.combine(cobrado_de, datetime.min.time())
        )
    if cobrado_ate:
        leads_query = leads_query.filter(
            models.Lead.cobrado_em <= datetime.combine(cobrado_ate, datetime.max.time())
        )
    if faixa:
        leads_query = leads_query.filter(models.Lead.faixa.in_(faixa))
    if cluster:
        leads_query = leads_query.filter(models.Lead.cluster.in_(cluster))

    leads_sem_parcelas = leads_query.filter(~models.Lead.parcelas.any()).count()

    parc_query = (
        db.query(
            models.LeadParcela.titulo_codigo,
            models.LeadParcela.empresa,
            models.LeadParcela.valor,
            models.LeadParcela.valor_cobrar,
            models.Lead.id.label("lead_id"),
            models.Lead.codigo_cliente,
            models.Lead.nome,
            models.Lead.faixa,
            models.Lead.cobrado_em,
        )
        .join(models.Lead, models.LeadParcela.lead_id == models.Lead.id)
        .filter(models.Lead.status == "cobrado")
    )
    if cobrado_de:
        parc_query = parc_query.filter(
            models.Lead.cobrado_em >= datetime.combine(cobrado_de, datetime.min.time())
        )
    if cobrado_ate:
        parc_query = parc_query.filter(
            models.Lead.cobrado_em <= datetime.combine(cobrado_ate, datetime.max.time())
        )
    if faixa:
        parc_query = parc_query.filter(models.Lead.faixa.in_(faixa))
    if cluster:
        parc_query = parc_query.filter(models.Lead.cluster.in_(cluster))
    if codigos_loja is not None:
        parc_query = parc_query.filter(models.LeadParcela.empresa.in_(codigos_loja))

    parcelas_db = parc_query.all()

    # Regra da Tarefa 5: conta como "pagou" quem quitou QUALQUER título em
    # aberto (não só o cobrado) dentro da janela — nunca em loop por
    # cliente/título, uma única consulta via CTE (ver seta_client).
    codigos_titulos = list({p.titulo_codigo for p in parcelas_db})
    situacoes: dict[str, dict] = {}
    if codigos_titulos:
        try:
            situacoes = seta_client.situacao_titulos(codigos_titulos)
        except seta_client.SetaIndisponivel as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    pares_cobranca = {
        (p.codigo_cliente, p.cobrado_em.date()) for p in parcelas_db if p.cobrado_em is not None
    }
    pagamentos: dict[tuple[str, date], date] = {}
    if pares_cobranca:
        try:
            pagamentos = seta_client.pagamentos_pos_cobranca(sorted(pares_cobranca), dias_janela)
        except seta_client.SetaIndisponivel as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    itens = []
    for p in parcelas_db:
        sit = situacoes.get(p.titulo_codigo)
        data_cobranca = p.cobrado_em.date() if p.cobrado_em else None
        pago = False
        renegociada = False
        valor_pago = Decimal("0.00")

        if data_cobranca and (p.codigo_cliente, data_cobranca) in pagamentos:
            pago = True
            valor_pago = Decimal(str(p.valor_cobrar or 0))
        elif sit and sit.get("status") == "S":
            renegociada = True

        itens.append(
            {
                "lead_id": p.lead_id,
                "codigo_cliente": p.codigo_cliente,
                "nome": p.nome,
                "faixa": p.faixa,
                "empresa": p.empresa,
                "titulo_codigo": p.titulo_codigo,
                "data_cobranca": data_cobranca,
                "valor_cobrar": p.valor_cobrar,
                "pago": pago,
                "renegociada": renegociada,
                "valor_pago": valor_pago,
            }
        )

    relatorio = montar_relatorio(itens, lojas_info=lojas_info, faixas_ordem=regras.nomes_faixa)
    return relatorio, leads_sem_parcelas, itens


def calcular_valor_a_pagar_brl(db: Session, cobrado_de: date | None, cobrado_ate: date | None) -> Decimal | None:
    """Custo das conversas de WhatsApp no período (Meta Pricing Analytics),
    somado entre todas as WABAs cadastradas e convertido pra BRL na cotação
    atual. A Meta não permite quebrar esse custo por faixa/loja (é por
    WABA/categoria de conversa), então só entra no total do relatório.
    Best-effort: qualquer falha (token não configurado, Meta fora do ar,
    câmbio indisponível) faz o valor voltar None em vez de derrubar o
    relatório inteiro, já que é informação complementar."""

    wabas = {
        w for (w,) in db.query(models.WhatsappNumber.waba_id).filter(models.WhatsappNumber.waba_id.isnot(None)).distinct()
    }
    if not wabas:
        return None

    inicio = cobrado_de or (date.today() - timedelta(days=30))
    fim = cobrado_ate or date.today()
    start_unix = int(datetime.combine(inicio, datetime.min.time()).timestamp())
    end_unix = int(datetime.combine(fim, datetime.max.time()).timestamp())

    async def _somar() -> Decimal:
        total_usd = Decimal("0.00")
        for waba_id in wabas:
            token = meta_client.token_da_waba(db, waba_id)
            client = meta_client.MetaClient(token)
            pontos = await client.conversation_analytics(waba_id, start_unix=start_unix, end_unix=end_unix)
            for p in pontos:
                total_usd += Decimal(str(p.get("cost", 0) or 0))
        cotacao = await cambio.cotacao_usd_brl()
        return (total_usd * Decimal(str(cotacao))).quantize(Decimal("0.01"))

    try:
        return asyncio.run(_somar())
    except Exception as exc:  # noqa: BLE001 - dado complementar, não pode derrubar o relatório
        logger.warning("Não foi possível calcular o valor a pagar à Meta: %s", exc)
        return None
