"""Gasto real com WhatsApp (Meta Pricing Analytics, em BRL) por dia, usado
no orçamento do Dashboard, no "valor a pagar" do relatório de efetividade e,
rateado por envio (`custo_por_envio`), no ROAS do "Por faixa" e da Efetividade.
A Meta devolve o custo na moeda de cobrança de cada WABA: USD é convertido pela
cotação do dia, BRL entra como veio."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .. import cache, cambio, consultas_fila, crypto, meta_client, models
from ..timezone import BUSINESS_TZ, hoje_br

logger = logging.getLogger(__name__)

# Mesmo prazo do Orçamento: o resumo do Dashboard se recalcula a cada 15 s e não
# pode ir à Meta a cada vez
GASTO_TTL_SEGUNDOS = 600

# pricing_category da Meta → categoria do Orçamento; autenticação e o resto entram
# em "outras", para a soma das categorias fechar com o gasto total.
CATEGORIAS = {"UTILITY": "utilitario", "MARKETING": "marketing", "MARKETING_LITE": "marketing", "SERVICE": "servico"}
CATEGORIA_OUTRAS = "outras"

# Moedas de cobrança da WABA que sabemos levar para BRL. Sem o campo currency
# (resposta antiga da Meta) o custo é tratado como USD, como sempre foi.
MOEDAS_SUPORTADAS = {"USD", "BRL"}

# Códigos de erro da Graph API que significam falta de acesso/permissão
_CODIGOS_PERMISSAO = {10, 100, 190, 200, 294}


@dataclass
class AvisoWaba:
    waba_id: str
    numeros: list[str]
    motivo: str


@dataclass
class CustoWhatsapp:
    por_dia: dict[date, Decimal] | None
    motivo: str | None = None
    avisos: list[AvisoWaba] = field(default_factory=list)
    # número exibido (ou phone_number da Meta) → gasto em BRL no período
    por_numero: dict[str, Decimal] = field(default_factory=dict)
    # (dia, WABA, número) → [gasto em BRL, mensagens cobradas]: exportação por dia
    por_dia_numero: dict[tuple[date, str, str], list] = field(default_factory=dict)
    # (dia, número, categoria de CATEGORIAS) → [gasto em BRL, mensagens cobradas]
    por_categoria: dict[tuple[date, str, str], list] = field(default_factory=dict)
    # (WABA, número, pricing_category da Meta, pricing_type) → [gasto em BRL, mensagens entregues],
    # sem filtro de categoria nem de tipo: base do painel de mensagens
    por_tipo_categoria: dict[tuple[str, str, str, str], list] = field(default_factory=dict)


# pricing_type da mensagem cobrada; qualquer outro (FREE_*) é gratuita
TIPO_COBRADA = "REGULAR"


def digitos(numero: str | None) -> str:
    return "".join(c for c in (numero or "") if c.isdigit())


def _descrever_erro(exc: Exception) -> str:
    if isinstance(exc, meta_client.MetaAPIError):
        erro = exc.payload.get("error", {}) if isinstance(exc.payload, dict) else {}
        codigo = erro.get("code")
        mensagem = erro.get("message") or str(exc)
        if codigo in _CODIGOS_PERMISSAO or exc.status_code in (401, 403):
            return f"sem permissão para ler os custos (erro {codigo}): {mensagem}"
        return f"erro da Meta ({exc.status_code}): {mensagem}"
    return str(exc)


def tokens_da_waba(db: Session, waba_id: str) -> list[str]:
    """Todos os tokens ativos que podem responder pela WABA — dos números dela
    e do cadastro em Configurações —, para tentar o próximo se um não tiver
    permissão."""

    tokens: list[str] = []
    fontes = (
        db.query(models.MetaToken)
        .join(models.WhatsappNumber, models.WhatsappNumber.meta_token_id == models.MetaToken.id)
        .filter(models.WhatsappNumber.waba_id == waba_id, models.MetaToken.ativo.is_(True))
        .order_by(models.MetaToken.created_at.asc())
        .all()
    ) + (
        db.query(models.MetaToken)
        .filter(models.MetaToken.waba_id == waba_id, models.MetaToken.ativo.is_(True))
        .order_by(models.MetaToken.created_at.asc())
        .all()
    )
    vistos = set()
    for t in fontes:
        if t.id in vistos or not t.token_cifrado:
            continue
        vistos.add(t.id)
        decifrado = crypto.decifrar(t.token_cifrado)
        if decifrado:
            tokens.append(decifrado)
    return tokens


async def consultar_waba(tokens: list[str], chamar) -> tuple[object | None, str | None]:
    """Roda `chamar(MetaClient)` com cada token da WABA até um responder:
    (resultado, None) ou (None, último erro) se nenhum respondeu."""

    erro = "nenhum token da Meta ativo para esta WABA"
    for token in tokens:
        try:
            return await chamar(meta_client.MetaClient(token)), None
        except Exception as exc:  # noqa: BLE001 - tenta o próximo token da WABA
            erro = _descrever_erro(exc)
    return None, erro


def gasto_por_categoria(custo: "CustoWhatsapp") -> dict[tuple[str, str], Decimal]:
    """Gasto real em BRL por (WABA, pricing_category da Meta) no período, já com câmbio
    e faixa de volume: base do rateio do custo por envio no painel de mensagens."""

    soma: dict[tuple[str, str], Decimal] = {}
    for (waba, _numero, categoria, _tipo), (gasto, _volume) in custo.por_tipo_categoria.items():
        soma[(waba, categoria)] = soma.get((waba, categoria), Decimal("0")) + gasto
    return soma


def consultar_custo(db: Session, inicio: date, fim: date) -> CustoWhatsapp:
    """Consulta direta à Meta, sem cache: quem lê o custo usa `custo_detalhado`.
    Custo de TODAS as WABAs conectadas (tokens ativos + números importados) no
    período, por dia e por número, com aviso de cada WABA que não pôde ser lida e
    quais números ficaram de fora do total."""

    numeros_por_waba: dict[str, list[str]] = {}
    for n in db.query(models.WhatsappNumber).filter(models.WhatsappNumber.waba_id.isnot(None)):
        lista = numeros_por_waba.setdefault(n.waba_id, [])
        if n.display_phone_number not in lista:
            lista.append(n.display_phone_number)
    for (w,) in db.query(models.MetaToken.waba_id).filter(models.MetaToken.ativo.is_(True)):
        if w:
            numeros_por_waba.setdefault(w, [])
    if not numeros_por_waba:
        return CustoWhatsapp(None, "Nenhuma WABA conectada (cadastre um token da Meta em Configurações).")

    start_unix = int(datetime.combine(inicio, time.min, BUSINESS_TZ).timestamp())
    fim_dt = datetime.combine(fim + timedelta(days=1), time.min, BUSINESS_TZ)
    # A Meta recusa período que termina no futuro
    end_unix = int(min(fim_dt, datetime.now(ZoneInfo("UTC"))).timestamp())
    if end_unix <= start_unix:
        return CustoWhatsapp({})

    tokens_por_waba = {w: tokens_da_waba(db, w) for w in numeros_por_waba}

    async def _buscar() -> tuple[list[dict], list[AvisoWaba]]:
        pontos: list[dict] = []
        avisos: list[AvisoWaba] = []
        for waba_id, numeros in numeros_por_waba.items():
            async def consultar(client, waba_id=waba_id):
                return await client.pricing_analytics(waba_id, start_unix=start_unix, end_unix=end_unix)

            resposta, erro = await consultar_waba(tokens_por_waba[waba_id], consultar)
            if resposta is None:
                avisos.append(AvisoWaba(waba_id, numeros, erro))
                continue
            moeda, pontos_waba = resposta
            moeda = (moeda or "USD").upper()
            if moeda not in MOEDAS_SUPORTADAS:
                # Converter com a cotação errada distorce o total; melhor avisar
                avisos.append(AvisoWaba(waba_id, numeros, f"moeda de cobrança {moeda} não suportada"))
            else:
                pontos.extend({**p, "waba_id": waba_id, "moeda": moeda} for p in pontos_waba)
        return pontos, avisos

    try:
        pontos, avisos = asyncio.run(_buscar())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao buscar custo na Meta: %s", exc)
        return CustoWhatsapp(None, f"Falha ao consultar a Meta: {exc}")

    for a in avisos:
        logger.warning("Custo da WABA %s indisponível: %s", a.waba_id, a.motivo)
    if len(avisos) == len(numeros_por_waba):
        return CustoWhatsapp(None, "; ".join(f"WABA {a.waba_id}: {a.motivo}" for a in avisos), avisos)

    # Só busca a cotação se alguma WABA cobra em dólar
    cotacao = Decimal("1")
    if any(p["moeda"] == "USD" for p in pontos):
        try:
            cotacao = Decimal(str(asyncio.run(cambio.cotacao_usd_brl())))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Câmbio indisponível: %s", exc)
            return CustoWhatsapp(None, f"Cotação do dólar indisponível: {exc}", avisos)

    exibicao = {
        digitos(n): n for numeros in numeros_por_waba.values() for n in numeros
    }
    por_dia: dict[date, Decimal] = {}
    por_categoria: dict[tuple[date, str, str], list] = {}
    por_numero: dict[str, Decimal] = {n: Decimal("0") for numeros in numeros_por_waba.values() for n in numeros}
    por_dia_numero: dict[tuple[date, str, str], list] = {}
    por_tipo_categoria: dict[tuple[str, str, str, str], list] = {}
    for p in pontos:
        if p.get("start") is None:
            continue
        dia = datetime.fromtimestamp(int(p["start"]), BUSINESS_TZ).date()
        custo = Decimal(str(p.get("cost", 0) or 0))
        if p["moeda"] == "USD":
            custo *= cotacao
        por_dia[dia] = por_dia.get(dia, Decimal("0")) + custo
        telefone = p.get("phone_number")
        chave = exibicao.get(digitos(telefone), telefone) if telefone else ""
        # Só conta mensagem cobrada: REGULAR na dimensão PRICING_TYPE (as
        # gratuitas vêm como FREE_*), ou custo > 0 se o tipo não vier.
        tipo = p.get("pricing_type")
        cobradas = int(p.get("volume", 0) or 0) if tipo == TIPO_COBRADA or (tipo is None and custo > 0) else 0
        linha = por_dia_numero.setdefault((dia, p.get("waba_id", ""), chave), [Decimal("0"), 0])
        linha[0] += custo
        linha[1] += cobradas
        linha = por_tipo_categoria.setdefault(
            (p.get("waba_id", ""), chave, p.get("pricing_category") or "", tipo or (TIPO_COBRADA if custo > 0 else "")),
            [Decimal("0"), 0],
        )
        linha[0] += custo
        linha[1] += int(p.get("volume", 0) or 0)
        categoria = CATEGORIAS.get(p.get("pricing_category"), CATEGORIA_OUTRAS)
        linha = por_categoria.setdefault((dia, chave, categoria), [Decimal("0"), 0])
        linha[0] += custo
        linha[1] += cobradas
        if telefone:
            por_numero[chave] = por_numero.get(chave, Decimal("0")) + custo
    return CustoWhatsapp(por_dia, None, avisos, por_numero, por_dia_numero, por_categoria, por_tipo_categoria)


def _para_json(r: CustoWhatsapp) -> dict:
    """CustoWhatsapp em estrutura guardável no Redis (chaves em tupla viram listas)."""

    def tabela(d: dict) -> list:
        return [[*(k if isinstance(k, tuple) else (k,)), *(v if isinstance(v, list) else [v])] for k, v in d.items()]

    dados = {
        "por_dia": None if r.por_dia is None else tabela(r.por_dia),
        "motivo": r.motivo,
        "avisos": [[a.waba_id, a.numeros, a.motivo] for a in r.avisos],
        "por_numero": tabela(r.por_numero),
        "por_dia_numero": tabela(r.por_dia_numero),
        "por_categoria": tabela(r.por_categoria),
        "por_tipo_categoria": tabela(r.por_tipo_categoria),
    }
    # Datas e Decimal viram texto já aqui: o resultado calculado e o lido do Redis são iguais
    return json.loads(json.dumps(dados, default=str))


def _de_json(d: dict) -> CustoWhatsapp:
    def tabela(linhas: list, n_chave: int) -> dict:
        return {tuple(l[:n_chave]): [Decimal(l[n_chave]), int(l[n_chave + 1])] for l in linhas}

    por_dia = None if d["por_dia"] is None else {date.fromisoformat(dia): Decimal(v) for dia, v in d["por_dia"]}
    return CustoWhatsapp(
        por_dia,
        d["motivo"],
        [AvisoWaba(*a) for a in d["avisos"]],
        {n: Decimal(v) for n, v in d["por_numero"]},
        {(date.fromisoformat(k[0]), *k[1:]): v for k, v in tabela(d["por_dia_numero"], 3).items()},
        {(date.fromisoformat(k[0]), *k[1:]): v for k, v in tabela(d["por_categoria"], 3).items()},
        tabela(d["por_tipo_categoria"], 4),
    )


def custo_detalhado(db: Session, inicio: date, fim: date) -> CustoWhatsapp:
    """Fonte única do custo da Meta: Orçamento, Mensagens e ROAS leem daqui. Guardado
    GASTO_TTL_SEGUNDOS no Redis por período, com o fim limitado a hoje (a Meta só vai
    até agora), então "1º ao dia 31" e "1º até hoje" são o mesmo snapshot. Falha não é
    guardada; sem Redis consulta a Meta direto."""

    fim = min(fim, hoje_br())
    try:
        dados = cache.obter_ou_calcular(
            cache.chave("custo-whatsapp-detalhado", {"inicio": inicio, "fim": fim}),
            lambda: _para_json(consultar_custo(db, inicio, fim)),
            GASTO_TTL_SEGUNDOS,
            guardar_se=lambda d: d["por_dia"] is not None,
        )
    except (cache.CacheIndisponivel, cache.CacheOcupado):
        return consultar_custo(db, inicio, fim)
    return _de_json(dados)


def gasto_diario_brl(db: Session, inicio: date, fim: date) -> tuple[dict[date, Decimal] | None, str | None]:
    """(gasto por dia em BRL, motivo) — gasto None quando não deu pra calcular
    nada; o motivo explica por quê."""

    r = custo_detalhado(db, inicio, fim)
    return r.por_dia, r.motivo or ("; ".join(f"WABA {a.waba_id}: {a.motivo}" for a in r.avisos) or None)


def custo_por_envio(db: Session, inicio: date, fim: date) -> tuple[dict[date, Decimal] | None, str | None]:
    """Custo médio de cada mensagem enviada pela fila, por dia: gasto do dia na
    Meta ÷ mensagens enviadas no dia (todas as faixas). A Meta não dá custo por
    mensagem nem por template, então o custo de uma faixa (ou de um lead) é este
    valor vezes os envios dela no dia. Dia sem envio fica de fora."""

    por_dia, motivo = gasto_diario_brl(db, inicio, fim)
    if por_dia is None:
        return None, motivo
    envios: dict[date, int] = {}
    for (dia, _faixa), n in consultas_fila.envios_por_dia(db, inicio, fim).items():
        envios[dia] = envios.get(dia, 0) + n
    return {dia: por_dia.get(dia, Decimal("0")) / n for dia, n in envios.items()}, motivo
