"""Cotação USD -> BRL para converter o custo de conversas da Meta (cobrado em
USD) pro orçamento em BRL (Tarefa 4/6). Usa uma API pública gratuita
(AwesomeAPI, sem chave) e cacheia em memória por um tempo curto — não precisa
de precisão de tempo real, só evitar bater na API a cada requisição."""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

_URL = "https://economia.awesomeapi.com.br/last/USD-BRL"
_CACHE_TTL_SEGUNDOS = 3600

_cache: dict[str, float] = {"valor": 0.0, "buscado_em": 0.0}


class CambioIndisponivel(Exception):
    pass


async def cotacao_usd_brl() -> float:
    """Cotação de venda do dólar em reais. Levanta CambioIndisponivel se a API
    pública falhar e não houver valor em cache pra usar como fallback."""

    agora = time.monotonic()
    if _cache["valor"] and (agora - _cache["buscado_em"]) < _CACHE_TTL_SEGUNDOS:
        return _cache["valor"]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(_URL)
            response.raise_for_status()
            payload = response.json()
        valor = float(payload["USDBRL"]["bid"])
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/formato vira fallback
        if _cache["valor"]:
            logger.warning("Falha ao atualizar cotação USD/BRL, usando valor em cache: %s", exc)
            return _cache["valor"]
        logger.warning("Falha ao consultar cotação USD/BRL: %s", exc)
        raise CambioIndisponivel(f"Não foi possível obter a cotação USD/BRL ({exc.__class__.__name__})") from exc

    _cache["valor"] = valor
    _cache["buscado_em"] = agora
    return valor
