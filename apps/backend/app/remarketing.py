"""Remarketing de clientes que desistiram no portal TopFamaRenegocie.

Uma vez por dia, antes do disparo, busca no Renegocie (mesma VPS) quem se
identificou no portal, quem simulou proposta sem fechar e quem tem acordo
lançado no SETA ainda ativo com a entrada vencida sem pagamento. Cada tipo é
um segmento com faixa própria
(número + template atribuídos em Faixas) e filtros configurados
na tela Remarketing. Daí em diante é o fluxo normal da fila: nada de
cobrar duas vezes no mesmo dia, blacklist, expiração no fim da janela.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session, selectinload

from . import campanhas_fixas, crypto, models, seta_client
from . import lojas as lojas_base
from .cobranca_base import _montar_cliente, _restaurar_linha_seta
from .cobranca_regras import faixa_de_compra
from .fila_automatica import clientes_bloqueados_hoje, enfileirar_clientes
from .leads_service import gerar_leads_de_clientes
from .regras_db import carregar_regras
from .timezone import BUSINESS_TZ
from .routers.blacklist import codigos_bloqueados
from .utils.phone import is_valid_phone

logger = logging.getLogger("remarketing")

SEGMENTOS = {
    "SO_IDENTIFICOU": "Clientes identificados no portal",
    "VIU_PROPOSTA": "Propostas simuladas",
    "ACORDO_ATIVO": "Acordo ativo com entrada não paga",
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
            faixa = models.Faixa(name=nome, active=True, tipo=models.TIPO_REMARKETING)
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
        raise RemarketingErro("Conexão com o Renegocie não configurada (Configurações → Conexões)")
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


def dia_do_evento(valor: str) -> date:
    """Data do evento no fuso de Brasília."""

    return _evento(valor).replace(tzinfo=timezone.utc).astimezone(BUSINESS_TZ).date()


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
    periodo: tuple[date, date] | None = None,
) -> dict[str, list[dict]]:
    """Por segmento ativo (ou os de `somente`, ligados ou não, para a prévia),
    os clientes que passam nos filtros, já com os dados do SETA (valor,
    atraso, telefone) prontos para a fila. `periodo` (só na prévia) troca a
    janela do segmento por um intervalo de datas do evento, no fuso de Brasília."""

    agora = agora or datetime.utcnow()
    regras_seg = {
        r.segmento: r
        for r in garantir_segmentos(db)
        if (r.segmento in somente if somente is not None else r.ativo)
    }
    resultado: dict[str, list[dict]] = {s: [] for s in regras_seg}
    if not regras_seg or not candidatos:
        return resultado

    def dentro(c: dict) -> bool:
        if periodo is not None:
            return periodo[0] <= dia_do_evento(c["evento_em"]) <= periodo[1]
        return _evento(c["evento_em"]) >= agora - timedelta(days=regras_seg[c["segmento"]].janela_dias)

    no_prazo = [c for c in candidatos if c.get("segmento") in regras_seg and c.get("person_ids") and dentro(c)]
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

    refs = sorted({c["referencia_seta"] for c in no_prazo if c["segmento"] == "ACORDO_ATIVO" and c.get("referencia_seta")})
    entradas_vencidas = seta_client.entradas_vencidas_em_aberto(refs) if refs else {}

    lojas_por_cobradora: dict[str, set[str] | None] = {}
    for segmento, regra in regras_seg.items():
        lojas_por_cobradora[segmento] = (
            set(lojas_base.codigos_por_atributos(db, cobradora=regra.cobradoras)) if regra.cobradoras else None
        )
    recontato = {s: _recontatados(db, r, agora) for s, r in regras_seg.items()}

    for c in no_prazo:
        segmento = c["segmento"]
        regra = regras_seg[segmento]
        # acordo pago, ainda no prazo da entrada ou que já sumiu do SETA fica de fora
        if segmento == "ACORDO_ATIVO" and c.get("referencia_seta") not in entradas_vencidas:
            continue
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
            {
                **cliente,
                "segmento": segmento,
                "evento_em": c["evento_em"],
                "referencia_seta": c.get("referencia_seta"),
                "entrada_vencimento": entradas_vencidas.get(c.get("referencia_seta")),
            }
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
        regra = regras_seg.get(segmento)
        if regra is None:
            totais[segmento] = 0
            continue
        enfileirados: list[dict] = []
        totais[segmento] = enfileirar_clientes(
            db,
            regra.faixa,
            lista,
            bloqueados=bloqueados,
            juros=juros,
            parcelas=parcelas,
            origem="no remarketing",
            enfileirados=enfileirados,
        )
        db.flush()
        # Como numa campanha (o remarketing é uma campanha fixa): lead da faixa
        # de atraso marcado com o segmento, que o envio marca como cobrado e
        # leva o cliente à régua no dia seguinte.
        gerar_leads_de_clientes(
            db, enfileirados, created_by=None, campanha_id=campanhas_fixas.id_campanha(segmento), parcelas=parcelas
        )
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
