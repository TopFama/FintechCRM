"""Regras do relatório de efetividade da cobrança (Tarefas 5 e 6): junta as
parcelas cobradas com a situação delas no SETA e com o custo real do
WhatsApp na Meta. Extraído de routers/reports.py — os endpoints HTTP ficam
finos, só validam parâmetros e devolvem o que este módulo calcula.

As duas funções ainda levantam HTTPException diretamente (SETA/Google fora
do ar), o que amarra esta "camada de serviço" ao FastAPI — um acoplamento
que ficou de fora do escopo desta primeira extração; o `raise` aqui é
convertido pelo próprio FastAPI na resposta HTTP igual seria se estivesse
no router, então não muda comportamento nenhum, só a localização do código."""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import google_client, lojas as lojas_base, models, seta_client
from ..timezone import hoje_br
from . import custo_whatsapp
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

    inicio = cobrado_de or (hoje_br() - timedelta(days=30))
    fim = cobrado_ate or hoje_br()
    por_dia, _motivo = custo_whatsapp.gasto_diario_brl(db, inicio, fim)
    if por_dia is None:
        return None
    return sum(por_dia.values(), Decimal("0")).quantize(Decimal("0.01"))
