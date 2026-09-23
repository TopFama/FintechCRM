"""Cotação USD -> BRL para converter o custo de conversas da Meta (cobrado em
USD) pro orçamento em BRL (Tarefa 4/6). Usa APIs públicas gratuitas
(AwesomeAPI, PTAX do Banco Central, open.er-api) e cacheia em memória por um tempo curto — não precisa
de precisão de tempo real, só evitar bater na API a cada requisição."""

import logging
import time
from datetime import timedelta

import httpx

from .timezone import hoje_br

logger = logging.getLogger(__name__)

_CACHE_TTL_SEGUNDOS = 3600

_cache: dict[str, float] = {"valor": 0.0, "buscado_em": 0.0}


class CambioIndisponivel(Exception):
    pass


async def _awesomeapi(client: httpx.AsyncClient) -> float:
    r = await client.get("https://economia.awesomeapi.com.br/last/USD-BRL")
    r.raise_for_status()
    return float(r.json()["USDBRL"]["bid"])


async def _ptax_bcb(client: httpx.AsyncClient) -> float:
    """PTAX de venda do Banco Central (oficial, sem chave). Busca uma janela
    de 10 dias porque fim de semana/feriado não tem cotação."""
    hoje = hoje_br()
    fmt = lambda d: d.strftime("%m-%d-%Y")  # noqa: E731
    r = await client.get(
        "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
        "CotacaoDolarPeriodo(dataInicial=@i,dataFinalCotacao=@f)",
        params={"@i": f"'{fmt(hoje - timedelta(days=10))}'", "@f": f"'{fmt(hoje)}'", "$format": "json"},
    )
    r.raise_for_status()
    return float(r.json()["value"][-1]["cotacaoVenda"])


async def _open_er_api(client: httpx.AsyncClient) -> float:
    r = await client.get("https://open.er-api.com/v6/latest/USD")
    r.raise_for_status()
    return float(r.json()["rates"]["BRL"])


# AwesomeAPI passou a responder erro (limite por IP) em servidor; as outras
# duas fontes gratuitas entram em sequência.
_FONTES = (_awesomeapi, _ptax_bcb, _open_er_api)


async def cotacao_usd_brl() -> float:
    """Cotação de venda do dólar em reais. Tenta as fontes em ordem; se todas
    falharem usa a última cotação boa (mesmo vencida). Só levanta
    CambioIndisponivel se nunca conseguiu nenhuma."""

    agora = time.monotonic()
    if _cache["valor"] and (agora - _cache["buscado_em"]) < _CACHE_TTL_SEGUNDOS:
        return _cache["valor"]

    falhas: list[str] = []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "FintechCRM/1.0"}) as client:
        for fonte in _FONTES:
            try:
                valor = await fonte(client)
                if valor > 0:
                    _cache["valor"] = valor
                    _cache["buscado_em"] = agora
                    return valor
            except Exception as exc:  # noqa: BLE001 - tenta a próxima fonte
                falhas.append(f"{fonte.__name__.strip('_')}: {exc.__class__.__name__}")

    if _cache["valor"]:
        logger.warning("Cotação USD/BRL não atualizada (%s), usando a última em cache", "; ".join(falhas))
        return _cache["valor"]
    logger.warning("Falha ao consultar cotação USD/BRL: %s", "; ".join(falhas))
    raise CambioIndisponivel(f"Não foi possível obter a cotação USD/BRL ({'; '.join(falhas)})")
