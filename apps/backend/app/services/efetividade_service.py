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
import re
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import campanhas_fixas, google_client, lojas as lojas_base, models, seta_client
from ..timezone import dia_br, hoje_br, inicio_do_dia_utc
from . import custo_whatsapp, pagamentos_seta
from ..regras_db import carregar_regras
from ..relatorio_efetividade import montar_relatorio

logger = logging.getLogger(__name__)






def filtrar_campanha(query, campanha: str | None):
    """Filtro "Campanha": vazio = tudo; "regua" = só envios da régua (faixas de
    atraso); id = só os envios daquela campanha."""
    if not campanha:
        return query
    if campanha == "regua":
        return query.filter(models.Lead.campanha_id == "")
    return query.filter(models.Lead.campanha_id == campanha)


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
    cobradora: list[str] | None = None,
    campanha: str | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[dict, int, list[dict]]:
    try:
        codigos_loja = lojas_base.combinar_lojas(
            db,
            loja=loja,
            regional=regional,
            estado=estado,
            cluster_inad=cluster_inad,
            cobradora=cobradora,
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
            models.Lead.cobrado_em >= inicio_do_dia_utc(cobrado_de)
        )
    if cobrado_ate:
        leads_query = leads_query.filter(
            models.Lead.cobrado_em < inicio_do_dia_utc(cobrado_ate + timedelta(days=1))
        )
    if faixa:
        leads_query = leads_query.filter(models.Lead.faixa.in_(faixa))
    if cluster:
        leads_query = leads_query.filter(models.Lead.cluster.in_(cluster))
    leads_query = filtrar_campanha(leads_query, campanha)

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
            models.Lead.campanha_id,
        )
        .join(models.Lead, models.LeadParcela.lead_id == models.Lead.id)
        .filter(models.Lead.status == "cobrado")
    )
    if cobrado_de:
        parc_query = parc_query.filter(
            models.Lead.cobrado_em >= inicio_do_dia_utc(cobrado_de)
        )
    if cobrado_ate:
        parc_query = parc_query.filter(
            models.Lead.cobrado_em < inicio_do_dia_utc(cobrado_ate + timedelta(days=1))
        )
    if faixa:
        parc_query = parc_query.filter(models.Lead.faixa.in_(faixa))
    if cluster:
        parc_query = parc_query.filter(models.Lead.cluster.in_(cluster))
    parc_query = filtrar_campanha(parc_query, campanha)
    # Filtro de loja só no fim: o valor pago é do cliente (todas as lojas) e é
    # repartido entre todas as parcelas da cobrança; filtrar antes jogava o
    # pagamento inteiro nas parcelas da loja filtrada
    parcelas_db = parc_query.all()

    # Regra da Tarefa 5: conta como "pagou" quem quitou QUALQUER título em
    # aberto (não só o cobrado) dentro da janela — nunca em loop por
    # cliente/título: baixas copiadas localmente (ver services/pagamentos_seta).
    codigos_titulos = list({p.titulo_codigo for p in parcelas_db})
    situacoes: dict[str, dict] = {}
    if codigos_titulos:
        try:
            situacoes = seta_client.situacao_titulos(codigos_titulos)
        except seta_client.SetaIndisponivel as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    pares_cobranca = {
        (p.codigo_cliente, dia_br(p.cobrado_em)) for p in parcelas_db if p.cobrado_em is not None
    }
    pagamentos: dict[tuple[str, date], date] = {}
    valores_pagos: dict[tuple[str, date], dict] = {}
    if pares_cobranca:
        try:
            # Recebimento = o que entrou de fato no SETA na janela (mesma soma do
            # relatório Quem pagou e do card do Dashboard), não o valor cobrado.
            pagamentos, valores_pagos = pagamentos_seta.analisar_pos_cobranca(
                db, sorted(pares_cobranca), dias_janela
            )
        except seta_client.SetaIndisponivel as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    # O SETA diz quanto o cliente pagou por (cliente, data da cobrança), não
    # por parcela: reparte proporcionalmente ao valor cobrado de cada parcela
    # daquela cobrança, pra somar certo por faixa e por loja.
    cobrado_por_par: dict[tuple[str, date], Decimal] = {}
    for p in parcelas_db:
        if p.cobrado_em is not None:
            par = (p.codigo_cliente, dia_br(p.cobrado_em))
            cobrado_por_par[par] = cobrado_por_par.get(par, Decimal("0")) + Decimal(str(p.valor_cobrar or 0))
    qtd_por_par: dict[tuple[str, date], int] = {}
    for p in parcelas_db:
        if p.cobrado_em is not None:
            par = (p.codigo_cliente, dia_br(p.cobrado_em))
            qtd_por_par[par] = qtd_por_par.get(par, 0) + 1
    ja_repartido: dict[tuple[str, date], Decimal] = {}
    vistos: dict[tuple[str, date], int] = {}

    def _parte_paga(par: tuple[str, date], valor_cobrar) -> Decimal:
        total = Decimal(str((valores_pagos.get(par) or {}).get("valor_pago") or 0))
        vistos[par] = vistos.get(par, 0) + 1
        if vistos[par] == qtd_por_par[par]:
            # última parcela leva o resto do arredondamento
            parte = total - ja_repartido.get(par, Decimal("0"))
        else:
            base = cobrado_por_par[par]
            peso = Decimal(str(valor_cobrar or 0)) / base if base else Decimal(1) / qtd_por_par[par]
            parte = (total * peso).quantize(Decimal("0.01"))
        ja_repartido[par] = ja_repartido.get(par, Decimal("0")) + parte
        return parte

    nomes_campanha = {
        c.id: re.sub(r" \(arquivada \w+\)$", "", c.nome)
        for c in db.query(models.Campanha).filter(models.Campanha.id.in_({p.campanha_id for p in parcelas_db} - {""}))
    }
    nomes_campanha.update({c["id"]: c["nome"] for c in campanhas_fixas.listar(db)})

    itens = []
    for p in parcelas_db:
        sit = situacoes.get(p.titulo_codigo)
        data_cobranca = dia_br(p.cobrado_em) if p.cobrado_em else None
        pago = False
        renegociada = False
        valor_pago = Decimal("0.00")

        if data_cobranca and (p.codigo_cliente, data_cobranca) in pagamentos:
            pago = True
            valor_pago = _parte_paga((p.codigo_cliente, data_cobranca), p.valor_cobrar)
        elif sit and sit.get("status") == "S":
            renegociada = True

        itens.append(
            {
                "lead_id": p.lead_id,
                "codigo_cliente": p.codigo_cliente,
                "nome": p.nome,
                "faixa": p.faixa,
                "campanha_id": p.campanha_id,
                "campanha": nomes_campanha.get(p.campanha_id, "Campanha excluída") if p.campanha_id else None,
                "empresa": p.empresa,
                "titulo_codigo": p.titulo_codigo,
                "data_cobranca": data_cobranca,
                "valor_cobrar": p.valor_cobrar,
                "pago": pago,
                "renegociada": renegociada,
                "valor_pago": valor_pago,
            }
        )

    if codigos_loja is not None:
        lojas_filtro = set(codigos_loja)
        itens = [i for i in itens if i["empresa"] in lojas_filtro]

    relatorio = montar_relatorio(itens, lojas_info=lojas_info, faixas_ordem=regras.nomes_faixa)
    if sort_by:
        ordenar_relatorio(relatorio, sort_by, sort_dir, regras.nomes_faixa)
    return relatorio, leads_sem_parcelas, itens


COLUNAS_ORDENAVEIS = (
    "faixa", "campanha", "loja", "loja_nome", "regional", "cluster_inad", "qtd_envios", "clientes_cobrados",
    "valor_cobrado", "clientes_pagaram", "valor_pago", "conversao_clientes", "recuperacao_valor",
)


def ordenar_relatorio(relatorio: dict, sort_by: str, sort_dir: str, faixas_ordem: list[str]) -> None:
    """Ordena as linhas por faixa e por loja pela coluna pedida, sobre o
    resultado inteiro. `faixa` segue a ordem de atraso das regras, não a
    alfabética; vazios vão sempre para o fim. Colunas que não existem numa
    das visões (ex.: `regional` na visão por faixa) deixam aquela visão como está."""

    ordem_faixa = {nome: i for i, nome in enumerate(faixas_ordem)}

    def valor(linha: dict):
        v = linha.get(sort_by)
        if sort_by == "faixa":
            return ordem_faixa.get(v, len(ordem_faixa))
        return v.upper() if isinstance(v, str) else v

    for chave in ("por_faixa", "por_loja", "por_campanha"):
        linhas = relatorio[chave]
        if not linhas or sort_by not in linhas[0]:
            continue
        preenchidas = [l for l in linhas if valor(l) is not None]
        vazias = [l for l in linhas if valor(l) is None]
        preenchidas.sort(key=valor, reverse=sort_dir == "desc")
        relatorio[chave] = preenchidas + vazias


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
