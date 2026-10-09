"""Regras do relatório de efetividade da cobrança (Tarefas 5 e 6): junta as
parcelas cobradas com a situação delas no SETA e com o custo real do
WhatsApp na Meta. Extraído de routers/reports.py — os endpoints HTTP ficam
finos, só validam parâmetros e devolvem o que este módulo calcula.

A parte cara (parcelas cobradas, baixas e situação dos títulos no SETA) vira
um *snapshot* no Redis por período, janela, faixa, cluster e campanha
(`_calcular_snapshot`); relatório, Excel, lista por cliente e Excel por
cliente derivam do mesmo snapshot (`obter_dados_efetividade`), e filtro de
loja e ordenação são aplicados depois, sem nova consulta ao SETA.

Falha do SETA ou do Redis sobe como veio (SetaIndisponivel, SetaOcupado,
CacheIndisponivel...): quem traduz para HTTP é o router (routers/comum.py).
Só o Google fora do ar (planilha de lojas) ainda vira HTTPException aqui."""

import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import cache, campanhas_fixas, google_client, lojas as lojas_base, models, seta_client
from ..database import SessionLocal
from ..timezone import dia_br, hoje_br, inicio_do_dia_utc
from . import custo_whatsapp, pagamentos_seta
from ..regras_db import carregar_regras
from ..relatorio_efetividade import montar_relatorio

logger = logging.getLogger(__name__)

# Os dados do SETA não precisam ser de agora: 5 min frescos; até 30 min depois
# o snapshot ainda é servido (marcado desatualizado) enquanto um recálculo único
# roda em segundo plano, ou quando o SETA falha.
EFETIVIDADE_TTL_SEGUNDOS = 300
EFETIVIDADE_VELHO_SEGUNDOS = 1800


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
    """(relatório, leads sem parcelas, itens por parcela). O relatório traz
    também `gerado_em` e `desatualizado` (snapshot servido depois do prazo)."""

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

    # Loja/regional/estado/cluster INAD/cobradora não entram na chave: o valor pago é
    # do cliente (todas as lojas) e o filtro de loja só recorta as parcelas no fim
    filtros = dict(
        cobrado_de=cobrado_de, cobrado_ate=cobrado_ate, dias_janela=dias_janela, faixa=faixa, cluster=cluster,
        campanha=campanha,
    )
    snap = cache.obter_snapshot(
        cache.chave("efetividade", filtros),
        lambda: _calcular_snapshot(**filtros),
        ttl_segundos=EFETIVIDADE_TTL_SEGUNDOS,
        velho=EFETIVIDADE_VELHO_SEGUNDOS,
    )
    itens = _restaurar_itens(snap.data["itens"])
    if codigos_loja is not None:
        lojas_filtro = set(codigos_loja)
        itens = [i for i in itens if i["empresa"] in lojas_filtro]
    _aplicar_custo_whatsapp(db, itens)

    relatorio = montar_relatorio(itens, lojas_info=lojas_info, faixas_ordem=regras.nomes_faixa)
    relatorio["gerado_em"] = datetime.fromtimestamp(snap.gerado_em, tz=timezone.utc)
    relatorio["desatualizado"] = snap.velho
    if sort_by:
        ordenar_relatorio(relatorio, sort_by, sort_dir, regras.nomes_faixa)
    return relatorio, snap.data["leads_sem_parcelas"], itens


def _restaurar_itens(itens: list[dict]) -> list[dict]:
    """O snapshot passa pelo Redis como JSON: devolve data e valores aos tipos
    originais (quem acabou de calcular já os tem)."""

    for i in itens:
        if isinstance(i["data_cobranca"], str):
            i["data_cobranca"] = date.fromisoformat(i["data_cobranca"])
        for campo in ("valor_cobrar", "valor_pago"):
            if i[campo] is not None and not isinstance(i[campo], Decimal):
                i[campo] = Decimal(str(i[campo]))
    return itens


def _calcular_snapshot(
    *,
    cobrado_de: date | None,
    cobrado_ate: date | None,
    dias_janela: int | None,
    faixa: list[str] | None,
    cluster: list[str] | None,
    campanha: str | None,
) -> dict:
    """Parcelas cobradas do período, já com pago/renegociada/valor pago, de todas
    as lojas. Pode rodar em segundo plano depois que a requisição acabou, por
    isso abre a própria sessão de banco."""

    with SessionLocal() as db:
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
        # Sem filtro de loja: o valor pago é do cliente (todas as lojas) e é
        # repartido entre todas as parcelas da cobrança; filtrar antes jogava o
        # pagamento inteiro nas parcelas da loja filtrada (o recorte é de quem usa o snapshot)
        parcelas_db = parc_query.all()

        # Regra da Tarefa 5: conta como "pagou" quem quitou QUALQUER título em
        # aberto (não só o cobrado) dentro da janela — nunca em loop por
        # cliente/título: baixas copiadas localmente (ver services/pagamentos_seta).
        pares_cobranca = {
            (p.codigo_cliente, dia_br(p.cobrado_em)) for p in parcelas_db if p.cobrado_em is not None
        }
        pagamentos: dict[tuple[str, date], date] = {}
        valores_pagos: dict[tuple[str, date], dict] = {}
        if pares_cobranca:
            # Recebimento = o que entrou de fato no SETA na janela (mesma soma do
            # relatório Quem pagou e do card do Dashboard), não o valor cobrado.
            pagamentos, valores_pagos = pagamentos_seta.analisar_pos_cobranca(
                db, sorted(pares_cobranca), dias_janela
            )

        # A situação no SETA só serve para marcar "renegociada" a parcela que não foi
        # paga: parcela de quem pagou nem entra na consulta
        codigos_titulos = list(
            {
                p.titulo_codigo
                for p in parcelas_db
                if p.cobrado_em is None or (p.codigo_cliente, dia_br(p.cobrado_em)) not in pagamentos
            }
        )
        situacoes: dict[str, dict] = seta_client.situacao_titulos(codigos_titulos) if codigos_titulos else {}

        # O SETA diz quanto o cliente pagou por (cliente, data da cobrança), não
        # por parcela: reparte proporcionalmente ao valor cobrado de cada parcela
        # daquela cobrança, pra somar certo por faixa e por loja.
        indices_por_par: dict[tuple[str, date], list[int]] = {}
        for i, p in enumerate(parcelas_db):
            if p.cobrado_em is not None:
                indices_por_par.setdefault((p.codigo_cliente, dia_br(p.cobrado_em)), []).append(i)
        parte_paga: dict[int, Decimal] = {}
        for par, indices in indices_por_par.items():
            if par in pagamentos:
                total = Decimal(str((valores_pagos.get(par) or {}).get("valor_pago") or 0))
                parte_paga.update(zip(indices, _repartir(total, [parcelas_db[i].valor_cobrar for i in indices])))

        nomes_campanha = {
            c.id: re.sub(r" \(arquivada \w+\)$", "", c.nome)
            for c in db.query(models.Campanha).filter(models.Campanha.id.in_({p.campanha_id for p in parcelas_db} - {""}))
        }
        nomes_campanha.update({c["id"]: c["nome"] for c in campanhas_fixas.listar(db)})

        itens = []
        for i, p in enumerate(parcelas_db):
            sit = situacoes.get(p.titulo_codigo)
            data_cobranca = dia_br(p.cobrado_em) if p.cobrado_em else None
            pago = False
            renegociada = False
            valor_pago = Decimal("0.00")

            if data_cobranca and (p.codigo_cliente, data_cobranca) in pagamentos:
                pago = True
                valor_pago = parte_paga[i]
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
        return {"itens": itens, "leads_sem_parcelas": leads_sem_parcelas}


def _repartir(total: Decimal, pesos: list) -> list[Decimal]:
    """Reparte o total proporcionalmente aos pesos (em partes iguais se todos são
    zero), em centavos; a última parte leva o resto do arredondamento."""

    pesos = [Decimal(str(p or 0)) for p in pesos]
    base = sum(pesos, Decimal("0"))
    partes = [(total * (p / base if base else Decimal(1) / len(pesos))).quantize(Decimal("0.01")) for p in pesos[:-1]]
    return partes + [total - sum(partes, Decimal("0"))]


def _aplicar_custo_whatsapp(db: Session, itens: list[dict]) -> None:
    """Custo do WhatsApp de cada parcela (base do ROAS): cada lead é um envio e
    leva o custo por envio do dia da cobrança (custo_whatsapp.custo_por_envio),
    repartido entre as parcelas dele pelo mesmo peso do valor pago. Fica fora do
    snapshot: a Meta fora do ar não estraga o cache do SETA. Sem custo da Meta,
    `custo_whatsapp` = None (ROAS "—")."""

    dias = [i["data_cobranca"] for i in itens if i["data_cobranca"]]
    por_envio = custo_whatsapp.custo_por_envio(db, min(dias), max(dias))[0] if dias else {}
    por_lead: dict[str, list[dict]] = {}
    for i in itens:
        por_lead.setdefault(i["lead_id"], []).append(i)
    for parcelas in por_lead.values():
        if por_envio is None:
            for i in parcelas:
                i["custo_whatsapp"] = None
            continue
        custo = por_envio.get(parcelas[0]["data_cobranca"], Decimal("0"))
        for i, parte in zip(parcelas, _repartir(custo, [i["valor_cobrar"] for i in parcelas])):
            i["custo_whatsapp"] = parte


COLUNAS_ORDENAVEIS = (
    "faixa", "campanha", "loja", "loja_nome", "regional", "cluster_inad", "qtd_envios", "clientes_cobrados",
    "valor_cobrado", "clientes_pagaram", "valor_pago", "conversao_clientes", "recuperacao_valor", "roas",
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
    atual. A Meta não quebra esse custo por faixa/loja (é por WABA/número): o
    total vem daqui e o ROAS de cada linha usa o rateio por envio
    (`_aplicar_custo_whatsapp`).
    Best-effort: qualquer falha (token não configurado, Meta fora do ar,
    câmbio indisponível) faz o valor voltar None em vez de derrubar o
    relatório inteiro, já que é informação complementar."""

    inicio = cobrado_de or (hoje_br() - timedelta(days=30))
    fim = cobrado_ate or hoje_br()
    por_dia, _motivo = custo_whatsapp.gasto_diario_brl(db, inicio, fim)
    if por_dia is None:
        return None
    return sum(por_dia.values(), Decimal("0")).quantize(Decimal("0.01"))
