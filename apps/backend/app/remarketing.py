"""Remarketing de clientes que desistiram no portal TopFamaRenegocie.

Uma vez por dia, antes do disparo, busca no Renegocie (mesma VPS) quem só se
identificou, viu a proposta e parou, cancelou a proposta ou teve o acordo
cancelado sem pagar a entrada. Cada tipo é um segmento com faixa própria
(número + template atribuídos em Faixas) e filtros configurados
na tela Remarketing. Daí em diante é o fluxo normal da fila: nada de
cobrar duas vezes no mesmo dia, blacklist, expiração no fim da janela.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session, selectinload

from . import crypto, models, seta_client
from . import lojas as lojas_base
from .cobranca_base import _montar_cliente, _restaurar_linha_seta
from .cobranca_regras import faixa_de_compra
from .fila_automatica import _fontes, clientes_bloqueados_hoje
from .regras_db import carregar_regras
from .routers.blacklist import codigos_bloqueados
from .utils.leads_xlsx import formatar_cpf, primeiro_nome
from .utils.phone import is_valid_phone, normalize_phone
from .variaveis_template import contexto_cliente, resolver_variaveis

logger = logging.getLogger("remarketing")

SEGMENTOS = {
    "SO_IDENTIFICOU": "Só se identificou",
    "VIU_PROPOSTA": "Viu a proposta e não fechou",
    "CANCELOU_PROPOSTA": "Cancelou a proposta",
    "ACORDO_SEM_ENTRADA": "Acordo cancelado sem pagar a entrada",
}
PREFIXO_FAIXA = "Remarketing: "
MAX_JANELA_DIAS = 180
# Só quem tem parcela vencida: quem já renegociou fica só com as parcelas do
# acordo, ainda a vencer, e não deve receber remarketing. O filtro de faixa de
# atraso, quando existe, é do segmento.
_SO_EM_ATRASO = [(1, None)]


# Trocado no ambiente de teste (e2e) por um httpx.MockTransport.
TRANSPORTE: httpx.BaseTransport | None = None


class RemarketingErro(Exception):
    pass


def nome_faixa(segmento: str) -> str:
    return PREFIXO_FAIXA + SEGMENTOS[segmento]


def garantir_segmentos(db: Session) -> list[models.RemarketingSegmento]:
    """Cria na primeira vez a regra (desligada) e a faixa de cada segmento."""

    existentes = {s.segmento: s for s in db.query(models.RemarketingSegmento)}
    criou = False
    for segmento in SEGMENTOS:
        if segmento in existentes:
            continue
        nome = nome_faixa(segmento)
        faixa = db.query(models.Faixa).filter(models.Faixa.name == nome).first()
        if faixa is None:
            faixa = models.Faixa(name=nome, active=True)
            db.add(faixa)
            db.flush()
        regra = models.RemarketingSegmento(
            segmento=segmento,
            faixa_id=faixa.id,
            ativo=False,
            janela_dias=30,
            recontato_dias=7,
            cobradoras=[],
            faixas_atraso=[],
            clusters=[],
            ultimo_resultado={},
        )
        db.add(regra)
        existentes[segmento] = regra
        criou = True
    if criou:
        db.commit()
    return [existentes[s] for s in SEGMENTOS]


def buscar_no_renegocie(db: Session, dias: int) -> list[dict]:
    config = db.query(models.IntegracaoRenegocie).first()
    if config is None:
        raise RemarketingErro("Conexão com o Renegocie não configurada (tela Remarketing)")
    chave = crypto.decifrar(config.chave_cifrada)
    if not chave:
        raise RemarketingErro("Não foi possível ler a chave do Renegocie; cadastre de novo")
    url = config.base_url.rstrip("/") + "/api/v1/integracoes/remarketing"
    try:
        with httpx.Client(transport=TRANSPORTE, timeout=30) as cliente:
            resposta = cliente.get(
                url,
                params={"dias": max(1, min(dias, MAX_JANELA_DIAS))},
                headers={"X-Integration-Key": chave},
            )
    except httpx.HTTPError as exc:
        raise RemarketingErro(f"Renegocie fora do ar ({exc.__class__.__name__})") from exc
    if resposta.status_code == 401:
        raise RemarketingErro("O Renegocie recusou a chave; gere outra no admin do Renegocie")
    if resposta.status_code != 200:
        raise RemarketingErro(f"Renegocie respondeu {resposta.status_code}")
    return resposta.json().get("clientes", [])


def _evento(valor: str) -> datetime:
    """Instante do evento em UTC ingênuo (como o resto do banco da app)."""

    instante = datetime.fromisoformat(valor)
    if instante.tzinfo is not None:
        instante = instante.astimezone(timezone.utc).replace(tzinfo=None)
    return instante


def _recontatados(db: Session, regra: models.RemarketingSegmento, agora: datetime) -> set[str]:
    """Quem recebeu (ou está na fila) deste segmento dentro do intervalo de recontato."""

    desde = agora - timedelta(days=regra.recontato_dias)
    return {
        codigo
        for (codigo,) in db.query(models.QueueItem.codigo_cliente).filter(
            models.QueueItem.faixa_id == regra.faixa_id,
            models.QueueItem.created_at >= desde,
            models.QueueItem.status != models.QueueStatus.error,
        )
    }


def selecionar(
    db: Session,
    candidatos: list[dict],
    agora: datetime | None = None,
    somente: set[str] | None = None,
) -> dict[str, list[dict]]:
    """Por segmento ativo (ou os de `somente`, ligados ou não, para a prévia),
    os clientes que passam nos filtros, já com os dados do SETA (valor,
    atraso, telefone) prontos para a fila."""

    agora = agora or datetime.utcnow()
    regras_seg = {
        r.segmento: r
        for r in garantir_segmentos(db)
        if (r.segmento in somente if somente is not None else r.ativo)
    }
    resultado: dict[str, list[dict]] = {s: [] for s in regras_seg}
    if not regras_seg or not candidatos:
        return resultado

    no_prazo = [
        c
        for c in candidatos
        if c.get("segmento") in regras_seg
        and c.get("person_ids")
        and _evento(c["evento_em"]) >= agora - timedelta(days=regras_seg[c["segmento"]].janela_dias)
    ]
    if not no_prazo:
        return resultado

    regras = carregar_regras(db)
    bl_codigos, bl_cpfs = codigos_bloqueados(db)
    codigos = sorted({str(p).strip() for c in no_prazo for p in c["person_ids"]})
    linhas = seta_client.buscar_base_cobranca(
        faixas=_SO_EM_ATRASO,
        codigos=codigos,
        bloqueados_codigos=bl_codigos,
        bloqueados_cpfs=bl_cpfs,
        juros=regras.juros,
    )
    por_codigo: dict[str, dict] = {}
    for bruta in linhas:
        r = _restaurar_linha_seta(bruta)
        faixa = regras.faixa_por_dias(r["dias_atraso"])
        cluster = regras.cluster_por_valor_pago(r["valor_pago"])
        cliente = _montar_cliente(
            r, faixa, cluster, regras.entra_no_whatsapp(cluster, faixa), faixa_de_compra(r["qtd_compras"])
        )
        por_codigo[cliente["codigo"]] = cliente

    refs = sorted({c["referencia_seta"] for c in no_prazo if c["segmento"] == "ACORDO_SEM_ENTRADA" and c.get("referencia_seta")})
    acordos_pagos = seta_client.acordos_com_parcela_paga(refs) if refs else set()

    lojas_por_cobradora: dict[str, set[str] | None] = {}
    for segmento, regra in regras_seg.items():
        lojas_por_cobradora[segmento] = (
            set(lojas_base.codigos_por_atributos(db, cobradora=regra.cobradoras)) if regra.cobradoras else None
        )
    recontato = {s: _recontatados(db, r, agora) for s, r in regras_seg.items()}

    for c in no_prazo:
        segmento = c["segmento"]
        regra = regras_seg[segmento]
        if segmento == "ACORDO_SEM_ENTRADA" and c.get("referencia_seta") in acordos_pagos:
            continue  # parcela com status 'B': o acordo foi pago
        # sem parcela vencida no SETA = já pagou, renegociou ou está na blacklist
        cliente = next((por_codigo[str(p).strip()] for p in c["person_ids"] if str(p).strip() in por_codigo), None)
        if cliente is None or cliente["codigo"] in recontato[segmento]:
            continue
        if regra.faixas_atraso and cliente["faixa"] not in regra.faixas_atraso:
            continue
        if regra.clusters and cliente["cluster"] not in regra.clusters:
            continue
        valor = Decimal(str(cliente["valor_cobrar"] or 0))
        if regra.valor_min is not None and valor < regra.valor_min:
            continue
        if regra.valor_max is not None and valor > regra.valor_max:
            continue
        lojas_ok = lojas_por_cobradora[segmento]
        if lojas_ok is not None and not {lojas_base.codigo_filial(l) for l in cliente["lojas"]} & lojas_ok:
            continue
        # O celular confirmado no portal vale mais que o do cadastro do SETA.
        if c.get("celular") and is_valid_phone(c["celular"]):
            cliente = {**cliente, "celular": c["celular"], "celular_original": c["celular"]}
        resultado[segmento].append(
            {**cliente, "segmento": segmento, "evento_em": c["evento_em"], "proposta": c.get("proposta")}
        )
    for lista in resultado.values():
        lista.sort(key=lambda x: x["evento_em"], reverse=True)
    return resultado


def enfileirar(db: Session, selecionados: dict[str, list[dict]]) -> dict[str, int]:
    """Coloca na fila da faixa de cada segmento. Mesmo bloqueio da fila
    automática: quem está pendente/reservado ou já foi cobrado hoje, em
    qualquer faixa, fica de fora."""

    if not any(selecionados.values()):
        return {s: 0 for s in selecionados}
    regras_seg = {
        r.segmento: r
        for r in db.query(models.RemarketingSegmento).options(
            selectinload(models.RemarketingSegmento.faixa)
            .selectinload(models.Faixa.envios)
            .selectinload(models.FaixaEnvio.template)
            .selectinload(models.Template.variables),
            selectinload(models.RemarketingSegmento.faixa).selectinload(models.Faixa.variable_mappings),
        )
    }
    bloqueados = clientes_bloqueados_hoje(db)
    juros = carregar_regras(db).juros
    todos = [c["codigo"] for lista in selecionados.values() for c in lista]
    parcelas = seta_client.buscar_parcelas_cobranca(todos, juros=juros) if todos else {}
    totais: dict[str, int] = {}

    for segmento, lista in selecionados.items():
        totais[segmento] = 0
        regra = regras_seg.get(segmento)
        faixa = regra.faixa if regra else None
        templates = {e.template_id: e.template for e in (faixa.envios if faixa else []) if e.active and e.template_id}
        if not templates:
            logger.warning("Remarketing '%s': faixa sem número/template ativo; %s cliente(s) ignorado(s)", segmento, len(lista))
            continue
        fontes_por_template = {tid: _fontes(faixa, tpl) for tid, tpl in templates.items()}
        for cliente in lista:
            if cliente["codigo"] in bloqueados or not cliente.get("celular") or not is_valid_phone(cliente["celular"]):
                continue
            contexto = contexto_cliente({**cliente, "parcelas": parcelas.get(cliente["codigo"], []), "juros": juros})
            faltando: list[str] = []
            por_template: dict[str, dict[str, str]] = {}
            for tid, fontes in fontes_por_template.items():
                valores: dict[str, str] = {}
                for v, fonte in fontes:
                    val = resolver_variaveis([fonte], contexto)[v.internal_name] if fonte else ""
                    if not val:
                        faltando.append(v.internal_name)
                    valores[v.internal_name] = val
                por_template[tid] = valores
            item = models.QueueItem(
                faixa_id=faixa.id,
                codigo_cliente=cliente["codigo"],
                nome=primeiro_nome(cliente["nome"]),
                cpf=formatar_cpf(cliente["cpfcnpj"]),
                valor=str(cliente["valor_cobrar"]),
                celular=normalize_phone(cliente["celular"]),
                celular_original=cliente.get("celular_original") or cliente["celular"],
                variables_json=next(iter(por_template.values())) if len(por_template) == 1 else por_template,
                status=models.QueueStatus.pending,
            )
            if faltando:
                item.status = models.QueueStatus.error
                item.error_message = f"Variável sem valor no remarketing: {', '.join(sorted(set(faltando)))}"
            else:
                totais[segmento] += 1
            db.add(item)
            bloqueados.add(cliente["codigo"])
    db.commit()
    return totais


def executar(db: Session) -> dict[str, dict]:
    """Busca, filtra e enfileira. Grava o resultado em cada segmento para a tela."""

    regras = [r for r in garantir_segmentos(db) if r.ativo]
    if not regras:
        return {}
    candidatos = buscar_no_renegocie(db, max(r.janela_dias for r in regras))
    selecionados = selecionar(db, candidatos)
    na_fila = enfileirar(db, selecionados)
    agora = datetime.utcnow()
    resumo = {}
    for regra in regras:
        resumo[regra.segmento] = {
            "encontrados": len(selecionados.get(regra.segmento, [])),
            "na_fila": na_fila.get(regra.segmento, 0),
        }
        regra.ultima_execucao = agora
        regra.ultimo_resultado = resumo[regra.segmento]
    db.commit()
    logger.info("Remarketing: %s", resumo)
    return resumo
