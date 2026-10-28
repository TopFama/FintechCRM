"""Painel de mensagens do Dashboard: as mini-tabelas do "Preços das mensagens" do
analytics da Meta (todas as mensagens, entregues por categoria, gratuitas,
pagas, cobrança aproximada) e, por template, entregues, lidas, cliques e
conversão, com filtro de telefone, WABA, período, template e campanha.

Fontes: custo e volume por categoria e tipo vêm de `custo_whatsapp.custo_detalhado`
(Pricing Analytics já convertido para BRL, uma consulta só), enviadas/entregues/
recebidas do analytics da WABA e lidas/cliques do template_analytics. A Meta não
filtra nada disso por template nem por campanha: com um deles marcado, os quadros
passam a contar os envios da fila (`QueueItem.template_id`) e o custo é a
quantidade vezes a tarifa unitária da categoria, que sai do próprio Pricing
Analytics (custo ÷ volume da mesma WABA e categoria no período). Lidas e cliques
só existem por 7 dias depois do envio e com os insights ativados na WABA."""

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cache, consultas_fila, models, seta_client
from ..timezone import BUSINESS_TZ, hoje_br
from . import custo_whatsapp, pagamentos_service

logger = logging.getLogger(__name__)

# Mesmo prazo do Orçamento: a Meta é lenta e o painel não precisa ser em tempo real
PAINEL_TTL_SEGUNDOS = 600  # guardado no Redis pelo router
# A Meta guarda 90 dias de analytics de template
DIAS_TEMPLATE_ANALYTICS = 90
# product_types do analytics da WABA: 0 = template, 2 = não-template, 100 = recebidas
TIPOS_ENVIADAS = [0, 2]
TIPOS_RECEBIDAS = [100]


def _unix(dia: date, fim: bool = False) -> int:
    momento = datetime.combine(dia + timedelta(days=1) if fim else dia, time.min, BUSINESS_TZ)
    # A Meta recusa período que termina no futuro
    return int(min(momento, datetime.now(ZoneInfo("UTC"))).timestamp())


def _quantidades(linhas: dict[str, int]) -> dict:
    return {"total": sum(linhas.values()), "por_categoria": linhas}


def _quadros_da_meta(
    custo: custo_whatsapp.CustoWhatsapp, wabas: set[str] | None, telefones: set[str] | None
) -> dict:
    """Entregues por categoria, gratuitas, pagas e cobrança total aproximada do
    Pricing Analytics, só das WABAs e números escolhidos."""

    entregues: dict[str, int] = {}
    pagas: dict[str, int] = {}
    gratuitas: dict[str, int] = {}
    gasto: dict[str, Decimal] = {}
    for (waba, numero, categoria, tipo), (valor, volume) in custo.por_tipo_categoria.items():
        if (wabas is not None and waba not in wabas) or (telefones is not None and custo_whatsapp.digitos(numero) not in telefones):
            continue
        categoria = categoria or "OUTRAS"
        entregues[categoria] = entregues.get(categoria, 0) + volume
        if tipo == custo_whatsapp.TIPO_COBRADA:
            pagas[categoria] = pagas.get(categoria, 0) + volume
        else:
            gratuitas[tipo or "GRATUITA"] = gratuitas.get(tipo or "GRATUITA", 0) + volume
        gasto[categoria] = gasto.get(categoria, Decimal("0")) + valor
    return {
        "entregues": _quantidades(entregues),
        "pagas": _quantidades(pagas),
        "gratuitas": {"total": sum(gratuitas.values()), "por_tipo": gratuitas},
        "cobranca": {
            "total_brl": sum(gasto.values(), Decimal("0")).quantize(Decimal("0.01")),
            "por_categoria": {c: v.quantize(Decimal("0.01")) for c, v in gasto.items()},
        },
    }


def _mensagens_da_meta(
    db: Session, de: date, ate: date, wabas: list[str], telefones_por_waba: dict[str, list[str]] | None
) -> tuple[dict, list[str]]:
    """Enviadas, entregues e recebidas (analytics da WABA) somando as WABAs;
    uma WABA sem leitura vira aviso e fica fora da soma."""

    resultado = {"enviadas": 0, "entregues": 0, "recebidas": 0}
    avisos: list[str] = []
    inicio, fim = _unix(de), _unix(ate, fim=True)

    async def buscar() -> None:
        for waba in wabas:
            telefones = (telefones_por_waba or {}).get(waba)

            async def consultar(client, waba=waba, telefones=telefones):
                enviadas = await client.message_analytics(
                    waba, start_unix=inicio, end_unix=fim, product_types=TIPOS_ENVIADAS, telefones=telefones
                )
                recebidas = await client.message_analytics(
                    waba, start_unix=inicio, end_unix=fim, product_types=TIPOS_RECEBIDAS, telefones=telefones
                )
                return enviadas, recebidas

            resposta, erro = await custo_whatsapp.consultar_waba(custo_whatsapp.tokens_da_waba(db, waba), consultar)
            if resposta is None:
                avisos.append(f"Mensagens da WABA {waba} indisponíveis: {erro}")
                continue
            enviadas, recebidas = resposta
            resultado["enviadas"] += sum(int(p.get("sent") or 0) for p in enviadas)
            resultado["entregues"] += sum(int(p.get("delivered") or 0) for p in enviadas)
            resultado["recebidas"] += sum(int(p.get("sent") or 0) for p in recebidas)

    asyncio.run(buscar())
    return resultado, avisos


def _cliques(clicked) -> int:
    """A Meta devolve os cliques por botão ([{type, button_content, count}])."""
    if isinstance(clicked, list):
        return sum(int(c.get("count") or 0) for c in clicked)
    return int(clicked or 0)


def _analytics_de_templates(
    db: Session, de: date, ate: date, templates: list[models.Template]
) -> tuple[dict[str, dict], list[str]]:
    """{template.id: {entregues, lidas, cliques}} do template_analytics, por WABA
    do template. WABA sem insights ativados ou sem permissão vira aviso."""

    avisos: list[str] = []
    limite = hoje_br() - timedelta(days=DIAS_TEMPLATE_ANALYTICS - 1)
    if de < limite:
        avisos.append(f"Lidas e cliques só vão até {DIAS_TEMPLATE_ANALYTICS} dias atrás: período cortado em {limite:%d/%m/%Y}")
        de = limite
    if de > ate:
        return {}, avisos
    inicio, fim = _unix(de), _unix(ate, fim=True)
    por_waba: dict[str, list[models.Template]] = {}
    for t in templates:
        if t.meta_template_id and t.waba_id:
            por_waba.setdefault(t.waba_id, []).append(t)
    por_meta_id = {t.meta_template_id: t.id for t in templates if t.meta_template_id}
    dados: dict[str, dict] = {}

    async def buscar() -> None:
        for waba, lista in por_waba.items():

            async def consultar(client, waba=waba, lista=lista):
                return await client.template_analytics(
                    waba, [t.meta_template_id for t in lista], start_unix=inicio, end_unix=fim
                )

            pontos, erro = await custo_whatsapp.consultar_waba(custo_whatsapp.tokens_da_waba(db, waba), consultar)
            if pontos is None:
                avisos.append(f"Lidas e cliques da WABA {waba} indisponíveis: {erro}")
                continue
            for p in pontos:
                alvo = por_meta_id.get(str(p.get("template_id")))
                if not alvo:
                    continue
                soma = dados.setdefault(alvo, {"entregues": 0, "lidas": 0, "cliques": 0})
                soma["entregues"] += int(p.get("delivered") or 0)
                soma["lidas"] += int(p.get("read") or 0)
                soma["cliques"] += _cliques(p.get("clicked"))

    asyncio.run(buscar())
    return dados, avisos


def _envios_da_fila(
    db: Session, de: date, ate: date, numeros: list[str] | None, templates: list[str], campanha: str
) -> list[dict]:
    """Envios (sent) do período por template e WABA, com os clientes cobrados.
    Mesmos filtros da fila: período em dias de Brasília e campanha pela faixa dela."""

    ini, fim = consultas_fila.limites_utc(de, ate)
    q = (
        select(
            models.QueueItem.template_id,
            models.WhatsappNumber.waba_id,
            models.QueueItem.codigo_cliente,
            func.count().label("envios"),
        )
        .select_from(models.QueueItem)
        .join(models.WhatsappNumber, models.QueueItem.whatsapp_number_id == models.WhatsappNumber.id, isouter=True)
        .where(
            models.QueueItem.status == models.QueueStatus.sent,
            consultas_fila.condicao_periodo(models.QueueItem.sent_at, ini, fim),
        )
        .group_by(models.QueueItem.template_id, models.WhatsappNumber.waba_id, models.QueueItem.codigo_cliente)
    )
    if numeros is not None:
        q = q.where(models.QueueItem.whatsapp_number_id.in_(numeros))
    if templates:
        q = q.where(models.QueueItem.template_id.in_(templates))
    if campanha:
        q = q.where(consultas_fila.filtro_campanha(db, models.QueueItem.faixa_id, campanha))
    return [dict(l._mapping) for l in db.execute(q)]


def _conversao(db: Session, de: date, ate: date, campanha: str) -> tuple[set[str] | None, str | None]:
    """Clientes cobrados no período que pagaram dentro da janela de Indicadores
    (mesma lista e regra do card de pagamentos do Dashboard e do Quem pagou)."""

    dias_janela = db.query(models.ParametrosCobranca.dias_janela_dashboard).scalar()
    try:
        linhas = pagamentos_service.snapshot_pagamentos(
            cobrado_de=de, cobrado_ate=ate, dias_janela=dias_janela, campanha=campanha or None, base="envios"
        ).data
    except seta_client.SetaIndisponivel:
        return None, "Conversão indisponível: sem conexão com o SETA"
    except (cache.CacheIndisponivel, cache.CacheOcupado):
        return None, "Conversão indisponível agora: tente de novo em instantes"
    return {l["codigo_cliente"] for l in linhas}, None


def montar(
    db: Session,
    de: date,
    ate: date,
    *,
    telefones: list[str],
    wabas: list[str],
    templates: list[str],
    campanha: str,
) -> dict:
    """Dados do painel (schemas.PainelMensagensOut). Levanta o que o cache
    levanta; falha da Meta ou do SETA vira aviso e deixa "—" no que depende dela."""

    avisos: list[str] = []
    numeros_db = db.query(models.WhatsappNumber).all()
    escolhidos = [
        n
        for n in numeros_db
        if (not telefones or n.id in telefones) and (not wabas or n.waba_id in wabas)
    ]
    filtra_numero = bool(telefones or wabas)
    ids_numero = [n.id for n in escolhidos] if filtra_numero else None
    wabas_alvo = {n.waba_id for n in escolhidos} if filtra_numero else None
    telefones_alvo = {custo_whatsapp.digitos(n.display_phone_number) for n in escolhidos} if telefones else None

    custo = custo_whatsapp.custo_detalhado(db, de, ate)
    meta_ok = custo.por_dia is not None
    for a in custo.avisos:
        avisos.append(f"Custo da WABA {a.waba_id} indisponível: {a.motivo}")
    if not meta_ok and custo.motivo:
        avisos.append(custo.motivo)

    envios = _envios_da_fila(db, de, ate, ids_numero, templates, campanha)
    por_template: dict[str, dict] = {}
    for e in envios:
        if not e["template_id"]:
            continue
        linha = por_template.setdefault(e["template_id"], {"enviados": 0, "clientes": set(), "por_waba": {}})
        linha["enviados"] += e["envios"]
        linha["clientes"].add(e["codigo_cliente"])
        waba = e["waba_id"] or ""
        linha["por_waba"][waba] = linha["por_waba"].get(waba, 0) + e["envios"]
    modelos = {
        t.id: t for t in db.query(models.Template).filter(models.Template.id.in_(list(por_template)))
    } if por_template else {}
    tarifas = custo_whatsapp.tarifas_unitarias(custo) if meta_ok else {}

    # Custo estimado de cada template: envios de cada WABA × tarifa unitária da categoria dela
    sem_tarifa: set[str] = set()
    for tid, linha in por_template.items():
        categoria = modelos[tid].category if tid in modelos else ""
        custo_tpl: Decimal | None = Decimal("0")
        for waba, qtd in linha["por_waba"].items():
            tarifa = tarifas.get((waba, categoria))
            if tarifa is None:
                sem_tarifa.add(f"{categoria or 'sem categoria'} na WABA {waba or 'desconhecida'}")
                custo_tpl = None
                break
            custo_tpl += tarifa * qtd
        linha["custo"] = custo_tpl
    if sem_tarifa:
        avisos.append("Sem tarifa no período para: " + "; ".join(sorted(sem_tarifa)))

    template_meta, avisos_meta = _analytics_de_templates(db, de, ate, list(modelos.values()))
    avisos += avisos_meta
    if (telefones or campanha) and template_meta:
        avisos.append("Entregues, lidas e cliques por template são da WABA inteira: a Meta não filtra por telefone nem campanha")
    pagaram, aviso_conversao = _conversao(db, de, ate, campanha) if por_template else (set(), None)
    if aviso_conversao:
        avisos.append(aviso_conversao)

    tabela = []
    for tid, linha in por_template.items():
        tpl = modelos.get(tid)
        meta = template_meta.get(tid)
        entregues_meta = meta["entregues"] if meta else None
        pagos = len(linha["clientes"] & pagaram) if pagaram is not None else None
        tabela.append(
            {
                "template_id": tid,
                "nome": tpl.name if tpl else "Template removido",
                "categoria": tpl.category if tpl else "",
                "enviados": linha["enviados"],
                "entregues": entregues_meta,
                "lidas": meta["lidas"] if meta else None,
                "cliques": meta["cliques"] if meta else None,
                "taxa_visualizacao": Decimal(meta["lidas"]) / entregues_meta if meta and entregues_meta else None,
                "taxa_cliques": Decimal(meta["cliques"]) / entregues_meta if meta and entregues_meta else None,
                "cobrados": len(linha["clientes"]),
                "pagaram": pagos,
                "conversao": Decimal(pagos) / len(linha["clientes"]) if pagos is not None and linha["clientes"] else None,
                "custo_brl": linha["custo"].quantize(Decimal("0.01")) if linha["custo"] is not None else None,
            }
        )
    tabela.sort(key=lambda l: -l["enviados"])

    saida = {"de": de, "ate": ate, "origem": "fila" if (templates or campanha) else "meta", "por_template": tabela}
    if templates or campanha:
        # A Meta não filtra por template nem campanha: quadros da fila, custo = quantidade × tarifa
        por_categoria: dict[str, int] = {}
        gasto: dict[str, Decimal] = {}
        gasto_completo = True
        for tid, linha in por_template.items():
            categoria = modelos[tid].category if tid in modelos else "OUTRAS"
            por_categoria[categoria] = por_categoria.get(categoria, 0) + linha["enviados"]
            if linha["custo"] is None:
                gasto_completo = False
            else:
                gasto[categoria] = gasto.get(categoria, Decimal("0")) + linha["custo"]
        saida.update(
            todas={"enviadas": sum(l["enviados"] for l in por_template.values()), "entregues": None, "recebidas": None},
            entregues=None,
            gratuitas=None,
            pagas=_quantidades(por_categoria),
            cobranca={
                "total_brl": sum(gasto.values(), Decimal("0")).quantize(Decimal("0.01")) if gasto_completo else None,
                "por_categoria": {c: v.quantize(Decimal("0.01")) for c, v in gasto.items()},
            },
        )
    elif meta_ok:
        wabas_conhecidas = sorted(
            wabas_alvo
            if wabas_alvo is not None
            else {n.waba_id for n in numeros_db if n.waba_id}
            | {w for (w,) in db.query(models.MetaToken.waba_id).filter(models.MetaToken.ativo.is_(True)) if w}
        )
        telefones_por_waba = (
            {w: [custo_whatsapp.digitos(n.display_phone_number) for n in escolhidos if n.waba_id == w] for w in wabas_conhecidas}
            if telefones
            else None
        )
        todas, avisos_msg = _mensagens_da_meta(db, de, ate, wabas_conhecidas, telefones_por_waba)
        avisos += avisos_msg
        saida.update(todas=todas, **_quadros_da_meta(custo, wabas_alvo, telefones_alvo))
    else:
        saida.update(todas=None, entregues=None, gratuitas=None, pagas=None, cobranca=None)
    saida["avisos"] = avisos
    return saida
