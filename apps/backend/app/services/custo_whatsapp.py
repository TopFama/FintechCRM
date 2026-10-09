"""Gasto real com WhatsApp (Meta Pricing Analytics, USD → BRL) por dia, usado
no orçamento do Dashboard, no "valor a pagar" do relatório de efetividade e,
rateado por envio (`custo_por_envio`), no ROAS do "Por faixa" e da Efetividade."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .. import cache, cambio, consultas_fila, crypto, meta_client, models
from ..timezone import BUSINESS_TZ

logger = logging.getLogger(__name__)

# Mesmo prazo do Orçamento: o resumo do Dashboard se recalcula a cada 15 s e não
# pode ir à Meta a cada vez
GASTO_TTL_SEGUNDOS = 600

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
    # número → mensagens que geraram custo no período
    mensagens_por_numero: dict[str, int] = field(default_factory=dict)
    # (dia, WABA, número) → [gasto em BRL, mensagens cobradas]: exportação por dia
    por_dia_numero: dict[tuple[date, str, str], list] = field(default_factory=dict)


def _digitos(numero: str | None) -> str:
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


def _tokens_da_waba(db: Session, waba_id: str) -> list[str]:
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


def custo_detalhado(db: Session, inicio: date, fim: date) -> CustoWhatsapp:
    """Custo de TODAS as WABAs conectadas (tokens ativos + números importados)
    no período, por dia e por número, com aviso de cada WABA que não pôde ser
    lida e quais números ficaram de fora do total."""

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

    tokens_por_waba = {w: _tokens_da_waba(db, w) for w in numeros_por_waba}

    async def _buscar() -> tuple[list[dict], list[AvisoWaba]]:
        pontos: list[dict] = []
        avisos: list[AvisoWaba] = []
        for waba_id, numeros in numeros_por_waba.items():
            tokens = tokens_por_waba[waba_id]
            if not tokens:
                avisos.append(AvisoWaba(waba_id, numeros, "nenhum token da Meta ativo para esta WABA"))
                continue
            erros: list[str] = []
            for token in tokens:
                try:
                    client = meta_client.MetaClient(token)
                    pontos.extend(
                        {**p, "waba_id": waba_id}
                        for p in await client.pricing_analytics(waba_id, start_unix=start_unix, end_unix=end_unix)
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - tenta o próximo token da WABA
                    erros.append(_descrever_erro(exc))
            else:
                avisos.append(AvisoWaba(waba_id, numeros, erros[-1]))
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

    try:
        cotacao = Decimal(str(asyncio.run(cambio.cotacao_usd_brl())))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Câmbio indisponível: %s", exc)
        return CustoWhatsapp(None, f"Cotação do dólar indisponível: {exc}", avisos)

    exibicao = {
        _digitos(n): n for numeros in numeros_por_waba.values() for n in numeros
    }
    por_dia: dict[date, Decimal] = {}
    mensagens: dict[str, int] = {}
    por_numero: dict[str, Decimal] = {n: Decimal("0") for numeros in numeros_por_waba.values() for n in numeros}
    por_dia_numero: dict[tuple[date, str, str], list] = {}
    for p in pontos:
        if p.get("start") is None:
            continue
        dia = datetime.fromtimestamp(int(p["start"]), BUSINESS_TZ).date()
        custo = Decimal(str(p.get("cost", 0) or 0)) * cotacao
        por_dia[dia] = por_dia.get(dia, Decimal("0")) + custo
        telefone = p.get("phone_number")
        chave = exibicao.get(_digitos(telefone), telefone) if telefone else ""
        # Só conta mensagem cobrada: REGULAR na dimensão PRICING_TYPE (as
        # gratuitas vêm como FREE_*), ou custo > 0 se o tipo não vier.
        tipo = p.get("pricing_type")
        cobradas = int(p.get("volume", 0) or 0) if tipo == "REGULAR" or (tipo is None and custo > 0) else 0
        linha = por_dia_numero.setdefault((dia, p.get("waba_id", ""), chave), [Decimal("0"), 0])
        linha[0] += custo
        linha[1] += cobradas
        if telefone:
            por_numero[chave] = por_numero.get(chave, Decimal("0")) + custo
            if cobradas:
                mensagens[chave] = mensagens.get(chave, 0) + cobradas
    return CustoWhatsapp(por_dia, None, avisos, por_numero, mensagens, por_dia_numero)


def gasto_diario_brl(db: Session, inicio: date, fim: date) -> tuple[dict[date, Decimal] | None, str | None]:
    """(gasto por dia em BRL, motivo) — gasto None quando não deu pra calcular
    nada; o motivo explica por quê. Guardado GASTO_TTL_SEGUNDOS no Redis (falha
    não é guardada); sem Redis consulta a Meta direto."""

    def calcular() -> dict:
        r = custo_detalhado(db, inicio, fim)
        motivo = r.motivo or ("; ".join(f"WABA {a.waba_id}: {a.motivo}" for a in r.avisos) or None)
        por_dia = None if r.por_dia is None else {d.isoformat(): str(v) for d, v in r.por_dia.items()}
        return {"por_dia": por_dia, "motivo": motivo}

    try:
        dados = cache.obter_ou_calcular(
            cache.chave("custo-whatsapp-dia", {"inicio": inicio, "fim": fim}),
            calcular,
            GASTO_TTL_SEGUNDOS,
            guardar_se=lambda d: d["por_dia"] is not None,
        )
    except (cache.CacheIndisponivel, cache.CacheOcupado):
        dados = calcular()
    if dados["por_dia"] is None:
        return None, dados["motivo"]
    return {date.fromisoformat(d): Decimal(v) for d, v in dados["por_dia"].items()}, dados["motivo"]


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
