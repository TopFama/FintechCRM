"""Cache Redis para consultas pesadas no SETA (a tabela de títulos passa de
27M de linhas — ver `seta_client.py`). Sem isso, cada requisição de
Cobrança/Leads refaz a mesma consulta ao ERP, que pode levar até o teto de
`SETA_DB_STATEMENT_TIMEOUT_SECONDS`.

`buscar_ou_iniciar` implementa um padrão simples de cálculo em segundo
plano: se o resultado já está em cache, devolve na hora; senão agenda o
cálculo numa thread e devolve "processing" imediatamente, sem segurar a
requisição HTTP. Quem chamou tenta de novo (poll) até vir "ready" — o
front-end já faz isso de forma transparente (ver `api.ts`). Uma trava no
Redis evita que duas requisições concorrentes disparem o mesmo cálculo
duas vezes.
"""

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import redis

from .config import settings

logger = logging.getLogger("cache")

RESULTADO_TTL_SEGUNDOS = 600  # 10 min: dado do SETA não precisa ser em tempo real
TRAVA_TTL_SEGUNDOS = 180  # se o processo cair no meio do cálculo, a trava expira sozinha

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cache-job")
_client: "redis.Redis | None" = None


class CacheIndisponivel(Exception):
    """Redis não configurado ou inalcançável. Mensagem segura para o usuário."""


def _redis() -> "redis.Redis":
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=3)
    return _client


def chave(prefixo: str, payload: dict) -> str:
    """Chave estável a partir de um payload de filtros (ordena as chaves e
    serializa datas/decimais como texto antes de gerar o hash)."""

    bruto = json.dumps(payload, sort_keys=True, default=str)
    return f"{prefixo}:{hashlib.sha256(bruto.encode()).hexdigest()}"


def buscar_ou_iniciar(chave_cache: str, calcular: Callable[[], Any]) -> dict:
    """{"status": "ready", "data": ...} se já tem no cache; senão agenda o
    cálculo em background (só uma vez por chave, mesmo com pedidos
    concorrentes) e devolve {"status": "processing", "data": None}."""

    try:
        client = _redis()
        bruto = client.get(f"resultado:{chave_cache}")
        if bruto is not None:
            return {"status": "ready", "data": json.loads(bruto)}

        obteve_trava = client.set(f"trava:{chave_cache}", "1", nx=True, ex=TRAVA_TTL_SEGUNDOS)
    except redis.RedisError as exc:
        raise CacheIndisponivel(f"Cache Redis indisponível ({exc.__class__.__name__})") from exc

    if obteve_trava:
        _executor.submit(_executar, chave_cache, calcular)
    return {"status": "processing", "data": None}


def _executar(chave_cache: str, calcular: Callable[[], Any]) -> None:
    try:
        resultado = calcular()
        _redis().set(f"resultado:{chave_cache}", json.dumps(resultado, default=str), ex=RESULTADO_TTL_SEGUNDOS)
    except Exception:
        logger.exception("Falha ao calcular relatório em background (chave=%s)", chave_cache)
    finally:
        try:
            _redis().delete(f"trava:{chave_cache}")
        except redis.RedisError:
            logger.exception("Falha ao liberar trava de cache (chave=%s)", chave_cache)


def obter_ou_calcular(chave_cache: str, calcular: Callable[[], Any], ttl_segundos: int = 300) -> Any:
    """Cache-aside simples (sem job em segundo plano): usado em consultas mais
    leves ao SETA, onde vale a pena guardar o resultado mas não compensa a
    complexidade do padrão "processing" acima."""

    try:
        client = _redis()
        bruto = client.get(f"resultado:{chave_cache}")
        if bruto is not None:
            return json.loads(bruto)
    except redis.RedisError as exc:
        raise CacheIndisponivel(f"Cache Redis indisponível ({exc.__class__.__name__})") from exc

    resultado = calcular()
    try:
        client.set(f"resultado:{chave_cache}", json.dumps(resultado, default=str), ex=ttl_segundos)
    except redis.RedisError:
        logger.exception("Falha ao gravar no cache (chave=%s)", chave_cache)
    return resultado
