"""Cache Redis e proteção do SETA contra consultas repetidas ou simultâneas.

O SETA (ERP) é um Postgres de produção e a tabela de títulos passa de 27M de
linhas (ver `seta_client.py`): a regra é `SETA -> poucas consultas -> Redis ->
aplicação`, nunca "cada requisição HTTP -> uma consulta nova". Tudo que o
relatório pesado guarda é um *snapshot* (`snap:<chave>`: o resultado e a hora
em que foi gerado), compartilhado entre usuários e abas.

Dois jeitos de pedir, ambos com single-flight (um cálculo por chave; os demais
reaproveitam o resultado):

- `buscar_ou_iniciar`: o cálculo roda numa thread e a requisição recebe
  "processing" na hora; quem chamou tenta de novo (`pollAsync` no front-end).
  Usado pela base de cobrança.
- `obter_snapshot` / `obter_ou_calcular`: quem pediu espera o resultado (o
  primeiro calcula, os outros esperam por ele em vez de calcular de novo).
  Usado por Dashboard e relatórios. Com `velho`, devolve na hora um snapshot já
  vencido (até `ttl + velho`) e atualiza uma vez em segundo plano; se o cálculo
  falha, devolve o último snapshot (marcado `velho`).

Proteções comuns:

- trava `lock:<chave>` com dono (UUID do job): só quem a pegou a solta (Lua
  compare-and-delete) e um batimento a renova enquanto o job vive, então um
  job lento não perde a trava nem apaga a de outro;
- no máximo `JOBS_SIMULTANEOS` jobs rodando e `JOBS_AGUARDANDO` esperando; acima
  disso o pedido não vira consulta (devolve "processing" e tenta de novo);
  job que ninguém pede há `INTERESSE_SEGUNDOS` (usuário mudou o filtro) é
  descartado sem ir ao SETA;
- falha do cálculo nunca vira snapshot e fica em quarentena (`erro:<chave>`)
  por `ERRO_QUARENTENA_SEGUNDOS`: as próximas tentativas recebem o erro na hora
  em vez de refazer a consulta a cada poll;
- Redis fora: `CacheIndisponivel`. Quem depende do SETA não faz consulta direta
  nesse caso (ver os routers); o limite global das consultas pesadas fica em
  `seta_client.consulta_pesada`.
"""

import hashlib
import json
import logging
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

import redis

from .config import settings

logger = logging.getLogger("cache")

RESULTADO_TTL_SEGUNDOS = 600  # 10 min: dado do SETA não precisa ser em tempo real

TRAVA_TTL_SEGUNDOS = 60  # o batimento renova; se o processo cair, a trava solta em até 1 min
TRAVA_RENOVA_A_CADA_SEGUNDOS = 20
TRAVA_VIDA_MAXIMA_SEGUNDOS = 1800  # job que passa disso perde a trava (não renova para sempre)

ERRO_QUARENTENA_SEGUNDOS = 30
ESPERA_RESULTADO_SEGUNDOS = 60  # quanto quem pede espera outro cálculo da mesma chave
REFRESH_IDADE_MINIMA_SEGUNDOS = 5  # "Atualizar agora" repetido reaproveita o que acabou de ser calculado
INTERESSE_SEGUNDOS = 45  # job aguardando que ninguém pede há mais que isso é descartado

JOBS_SIMULTANEOS = 2  # igual ao limite de consultas pesadas ao SETA (seta_client)
JOBS_AGUARDANDO = 4

_executor = ThreadPoolExecutor(max_workers=JOBS_SIMULTANEOS, thread_name_prefix="cache-job")
_client: "redis.Redis | None" = None
_estado = threading.Lock()
_jobs = 0  # admitidos e ainda não terminados (executando + aguardando)
_executando = 0
_visto: dict[str, float] = {}
_contadores: Counter = Counter()


class CacheIndisponivel(Exception):
    """Redis não configurado ou inalcançável. Mensagem segura para o usuário."""


class CalculoFalhou(CacheIndisponivel):
    """O cálculo falhou há pouco (quarentena): devolve a mesma mensagem sem
    refazer a consulta. Mensagem segura para o usuário."""


class CacheOcupado(Exception):
    """A mesma consulta segue em cálculo por mais tempo do que vale esperar.
    Pedir de novo daqui a pouco; não é falha do SETA."""

    quarentena = False


@dataclass
class Snapshot:
    data: Any
    gerado_em: float  # epoch, para mostrar a idade do dado
    velho: bool = False  # servido depois do prazo (atualização em segundo plano ou falha ao atualizar)


def _redis() -> "redis.Redis":
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=5
        )
    return _client


def redis_cliente() -> "redis.Redis":
    """O mesmo cliente, para quem guarda outra coisa no Redis (painel_tempo_real)."""
    return _redis()


@contextmanager
def _acesso():
    try:
        yield
    except redis.RedisError as exc:
        raise CacheIndisponivel(f"Cache Redis indisponível ({exc.__class__.__name__})") from exc


def metricas() -> dict:
    """Jobs rodando/aguardando e contagens desde que o processo subiu (hits,
    misses, stale, jobs iniciados/reutilizados/recusados/descartados, falhas)."""

    with _estado:
        return {"jobs_ativos": _executando, "jobs_aguardando": _jobs - _executando, **_contadores}


def _contar(evento: str) -> None:
    with _estado:
        _contadores[evento] += 1


def _nome(chave_cache: str) -> str:
    """Prefixo e começo do hash: identifica a consulta no log sem expor filtros."""

    prefixo, _, resto = chave_cache.partition(":")
    return f"{prefixo}:{resto[:8]}"


def _canonico(valor: Any) -> Any:
    if isinstance(valor, dict):
        itens = {str(k): _canonico(v) for k, v in valor.items()}
        return {k: v for k, v in itens.items() if v is not None and v != [] and v != {}}
    if isinstance(valor, (list, tuple, set, frozenset)):
        return sorted((_canonico(v) for v in valor), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    return valor


def chave(prefixo: str, payload: dict) -> str:
    """Chave estável a partir de um payload de filtros: listas ordenadas (a
    ordem dos filtros não muda a chave), filtro vazio igual a filtro ausente,
    datas e decimais como texto, tudo num hash."""

    bruto = json.dumps(_canonico(payload), sort_keys=True, default=str)
    return f"{prefixo}:{hashlib.sha256(bruto.encode()).hexdigest()}"


# --- Trava com dono ------------------------------------------------------------

_LUA_LIBERAR = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
LUA_RENOVAR = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) end return 0"


class _Trava:
    """`lock:<chave>` = UUID desta aquisição. `liberar` só apaga se a trava
    ainda é esta (o TTL pode ter vencido e outro job ter pegado uma nova)."""

    def __init__(self, chave_cache: str):
        self.nome = f"lock:{chave_cache}"
        self.chave_cache = chave_cache
        self.token = uuid.uuid4().hex
        self._parar = threading.Event()

    def adquirir(self, registrar: bool = True) -> bool:
        """`registrar=False` nas tentativas repetidas de quem espera, para o log
        e os contadores contarem uma vez por pedido."""

        obteve = bool(_redis().set(self.nome, self.token, nx=True, ex=TRAVA_TTL_SEGUNDOS))
        if obteve:
            threading.Thread(target=self._batimento, daemon=True, name="cache-trava").start()
        elif registrar:
            _contar("travas_ocupadas")
            logger.info("cache trava ocupada chave=%s", _nome(self.chave_cache))
        return obteve

    def _batimento(self) -> None:
        inicio = time.monotonic()
        while not self._parar.wait(TRAVA_RENOVA_A_CADA_SEGUNDOS):
            if time.monotonic() - inicio > TRAVA_VIDA_MAXIMA_SEGUNDOS:
                logger.warning("cache trava deixou de ser renovada (vida máxima) chave=%s", _nome(self.chave_cache))
                return
            try:
                if not _redis().eval(LUA_RENOVAR, 1, self.nome, self.token, TRAVA_TTL_SEGUNDOS):
                    logger.warning("cache trava perdida durante o cálculo chave=%s", _nome(self.chave_cache))
                    return
            except redis.RedisError:
                logger.warning("cache falha ao renovar a trava chave=%s", _nome(self.chave_cache))

    def liberar(self) -> None:
        self._parar.set()
        try:
            _redis().eval(_LUA_LIBERAR, 1, self.nome, self.token)
        except redis.RedisError:
            logger.exception("Falha ao liberar trava de cache (chave=%s)", _nome(self.chave_cache))


# --- Snapshot e erro -------------------------------------------------------------


def _ler(chave_cache: str) -> Snapshot | None:
    bruto = _redis().get(f"snap:{chave_cache}")
    if bruto is None:
        return None
    envelope = json.loads(bruto)
    return Snapshot(envelope["d"], envelope["g"])


def _gravar(chave_cache: str, data: Any, fresco: int, velho: int) -> float:
    """Guarda o snapshot e devolve a hora em que foi gerado."""

    gerado_em = time.time()
    _redis().set(f"snap:{chave_cache}", json.dumps({"g": gerado_em, "d": data}, default=str), ex=fresco + velho)
    return gerado_em


def _idade(snap: Snapshot) -> float:
    return time.time() - snap.gerado_em


def _registrar_erro(chave_cache: str, exc: Exception) -> None:
    """Põe a falha em quarentena. Erro de capacidade (`quarentena = False`) não:
    é só pedir de novo."""

    if not getattr(exc, "quarentena", True):
        return
    mensagem = str(exc) if getattr(exc, "mensagem_segura", False) else "Falha ao calcular o relatório. Tente de novo em instantes"
    try:
        _redis().set(f"erro:{chave_cache}", mensagem, ex=ERRO_QUARENTENA_SEGUNDOS)
    except redis.RedisError:
        logger.exception("Falha ao registrar erro do cálculo (chave=%s)", _nome(chave_cache))


def _erro_recente(chave_cache: str) -> str | None:
    return _redis().get(f"erro:{chave_cache}")


# --- Jobs em segundo plano -------------------------------------------------------


def _marcar_visto(chave_cache: str) -> None:
    agora = time.monotonic()
    with _estado:
        _visto[chave_cache] = agora
        if len(_visto) > 500:
            for k in [k for k, t in _visto.items() if agora - t > INTERESSE_SEGUNDOS]:
                del _visto[k]


def _ainda_interessa(chave_cache: str) -> bool:
    with _estado:
        visto = _visto.get(chave_cache)
    return visto is not None and time.monotonic() - visto <= INTERESSE_SEGUNDOS


def _admitir() -> bool:
    """Reserva lugar para um job (executando ou aguardando). Cheio, recusa."""

    global _jobs
    with _estado:
        if _jobs >= JOBS_SIMULTANEOS + JOBS_AGUARDANDO:
            _contadores["jobs_recusados"] += 1
            recusado = True
        else:
            _jobs += 1
            recusado = False
    return not recusado


_ultimo_aviso_recusa = 0.0


def _avisar_recusa(chave_cache: str) -> None:
    """Capacidade cheia: cada recusa conta, mas o aviso sai no máximo a cada 5 s
    (cada aba que tenta de novo recusaria e avisaria de novo)."""

    global _ultimo_aviso_recusa
    agora = time.monotonic()
    if agora - _ultimo_aviso_recusa >= 5:
        _ultimo_aviso_recusa = agora
        logger.warning("cache job recusado (capacidade) chave=%s %s", _nome(chave_cache), metricas())


def _iniciar_job(
    chave_cache: str,
    calcular: Callable[[], Any],
    trava: _Trava,
    fresco: int,
    velho: int = 0,
    guardar_se: Callable[[Any], bool] | None = None,
) -> bool:
    """Agenda o cálculo (já com a trava na mão) numa thread. Sem lugar na fila,
    solta a trava e devolve False: nada é consultado."""

    if not _admitir():
        trava.liberar()
        _avisar_recusa(chave_cache)
        return False
    _marcar_visto(chave_cache)
    _contar("jobs_iniciados")
    logger.info("cache job iniciado chave=%s", _nome(chave_cache))
    _executor.submit(_executar, chave_cache, calcular, trava, fresco, velho, guardar_se)
    return True


def _executar(
    chave_cache: str,
    calcular: Callable[[], Any],
    trava: _Trava,
    fresco: int,
    velho: int,
    guardar_se: Callable[[Any], bool] | None,
) -> None:
    global _jobs, _executando
    iniciou = False
    inicio = time.monotonic()
    try:
        if not _ainda_interessa(chave_cache):
            _contar("jobs_descartados")
            logger.info("cache job descartado (ninguém aguarda) chave=%s", _nome(chave_cache))
            return
        with _estado:
            _executando += 1
        iniciou = True
        resultado = calcular()
        if guardar_se is None or guardar_se(resultado):
            _gravar(chave_cache, resultado, fresco, velho)
        logger.info("cache job concluído chave=%s duracao=%.1fs %s", _nome(chave_cache), time.monotonic() - inicio, metricas())
    except Exception as exc:
        _contar("falhas")
        logger.exception("Falha ao calcular relatório em background (chave=%s)", _nome(chave_cache))
        _registrar_erro(chave_cache, exc)
    finally:
        with _estado:
            _jobs -= 1
            if iniciou:
                _executando -= 1
        trava.liberar()


def buscar_ou_iniciar(chave_cache: str, calcular: Callable[[], Any]) -> dict:
    """{"status": "ready", "data": ...} se já tem no cache; senão agenda o
    cálculo em background (só uma vez por chave, mesmo com pedidos
    concorrentes) e devolve {"status": "processing", "data": None}. Também
    devolve "processing" quando não há lugar para mais um job (quem pediu
    tenta de novo). Levanta CalculoFalhou se o último cálculo falhou há pouco."""

    with _acesso():
        _marcar_visto(chave_cache)
        snap = _ler(chave_cache)
        if snap is not None and _idade(snap) <= RESULTADO_TTL_SEGUNDOS:
            _contar("hits")
            logger.info("cache hit chave=%s idade=%.0fs", _nome(chave_cache), _idade(snap))
            return {"status": "ready", "data": snap.data}
        erro = _erro_recente(chave_cache)
        if erro is not None:
            raise CalculoFalhou(erro)
        trava = _Trava(chave_cache)
        if not trava.adquirir():
            _contar("jobs_reutilizados")
            return {"status": "processing", "data": None}
        # o job anterior pode ter acabado entre a leitura e a trava
        snap = _ler(chave_cache)
        if snap is not None and _idade(snap) <= RESULTADO_TTL_SEGUNDOS:
            trava.liberar()
            return {"status": "ready", "data": snap.data}
        _contar("misses")
        logger.info("cache miss chave=%s", _nome(chave_cache))
        _iniciar_job(chave_cache, calcular, trava, RESULTADO_TTL_SEGUNDOS)
        return {"status": "processing", "data": None}


def obter_snapshot(
    chave_cache: str,
    calcular: Callable[[], Any],
    ttl_segundos: int = 300,
    reaproveitar: bool = True,
    guardar_se: Callable[[Any], bool] | None = None,
    velho: int = 0,
) -> Snapshot:
    """Snapshot da chave, calculando só se preciso e uma vez só (single-flight).

    - dentro de `ttl_segundos`: devolve na hora;
    - `reaproveitar=False` ("Atualizar agora"): recalcula, mas um clique repetido
      não recalcula (reaproveita o que tem menos de REFRESH_IDADE_MINIMA_SEGUNDOS)
      e quem chega com um cálculo da chave em andamento espera esse mesmo;
    - `velho > 0`: de `ttl` até `ttl + velho` devolve o snapshot vencido (marcado
      `velho`) e atualiza uma vez em segundo plano, que por isso precisa de
      `calcular` com sessão de banco própria; e, se o cálculo falhar, devolve o
      último snapshot em vez do erro;
    - `guardar_se` evita guardar resultado ruim (ex.: integração fora do ar);
    - falha do cálculo nunca é guardada como snapshot.

    Levanta CacheIndisponivel (Redis fora), CalculoFalhou (falhou há pouco, sem
    snapshot para servir) e CacheOcupado (outro cálculo da chave passou de
    ESPERA_RESULTADO_SEGUNDOS); o erro do próprio `calcular` sobe como veio."""

    prazo = time.monotonic() + ESPERA_RESULTADO_SEGUNDOS
    primeira_tentativa = True
    while True:
        with _acesso():
            snap = _ler(chave_cache)
            idade = _idade(snap) if snap is not None else None
            if snap is not None and idade <= (ttl_segundos if reaproveitar else REFRESH_IDADE_MINIMA_SEGUNDOS):
                _contar("hits")
                logger.info("cache hit chave=%s idade=%.0fs", _nome(chave_cache), idade)
                return snap
            servivel = snap is not None and idade <= ttl_segundos + velho  # velho == 0: nunca serve vencido
            erro = _erro_recente(chave_cache)
            if erro is not None:
                if servivel:
                    return _servir_velho(chave_cache, snap, "erro recente")
                raise CalculoFalhou(erro)
            trava = _Trava(chave_cache)
            if not trava.adquirir(registrar=primeira_tentativa):
                if primeira_tentativa:
                    _contar("jobs_reutilizados")
                primeira_tentativa = False
                if servivel and reaproveitar:
                    return _servir_velho(chave_cache, snap, "atualização em andamento")
            else:
                return _calcular_com_trava(
                    chave_cache, calcular, trava, ttl_segundos, reaproveitar, guardar_se, velho
                )
        if time.monotonic() > prazo:
            if servivel:
                return _servir_velho(chave_cache, snap, "cálculo em andamento por tempo demais")
            raise CacheOcupado("A mesma consulta ainda está sendo calculada. Tente de novo em instantes")
        time.sleep(0.25)


def _servir_velho(chave_cache: str, snap: Snapshot, motivo: str) -> Snapshot:
    _contar("stale")
    logger.info("cache stale chave=%s idade=%.0fs motivo=%s", _nome(chave_cache), _idade(snap), motivo)
    return Snapshot(snap.data, snap.gerado_em, velho=True)


def _calcular_com_trava(
    chave_cache: str,
    calcular: Callable[[], Any],
    trava: _Trava,
    ttl_segundos: int,
    reaproveitar: bool,
    guardar_se: Callable[[Any], bool] | None,
    velho: int,
) -> Snapshot:
    """Já com a trava: confere de novo (o outro cálculo pode ter acabado agora),
    atualiza em segundo plano se há snapshot vencido que se pode servir, senão
    calcula aqui mesmo."""

    entregue = False
    try:
        with _acesso():
            snap = _ler(chave_cache)
        if snap is not None:
            idade = _idade(snap)
            if idade <= (ttl_segundos if reaproveitar else REFRESH_IDADE_MINIMA_SEGUNDOS):
                _contar("hits")
                return snap
            if reaproveitar and velho and idade <= ttl_segundos + velho:
                entregue = True  # a trava passa ao job (ou é solta por ele se não couber na fila)
                _iniciar_job(chave_cache, calcular, trava, ttl_segundos, velho, guardar_se)
                return _servir_velho(chave_cache, snap, "atualizando em segundo plano")
        _contar("misses")
        logger.info("cache miss chave=%s", _nome(chave_cache))
        inicio = time.monotonic()
        try:
            resultado = calcular()
        except Exception as exc:
            _contar("falhas")
            if snap is not None and velho and _idade(snap) <= ttl_segundos + velho:
                logger.warning("cache servido após falha chave=%s erro=%s", _nome(chave_cache), exc.__class__.__name__)
                _contar("servido_apos_falha")
                return Snapshot(snap.data, snap.gerado_em, velho=True)
            with _acesso():
                _registrar_erro(chave_cache, exc)
            raise
        logger.info("cache calculado chave=%s duracao=%.1fs", _nome(chave_cache), time.monotonic() - inicio)
        gerado_em = time.time()
        if guardar_se is None or guardar_se(resultado):
            try:
                gerado_em = _gravar(chave_cache, resultado, ttl_segundos, velho)
            except redis.RedisError:
                logger.exception("Falha ao gravar no cache (chave=%s)", _nome(chave_cache))
        return Snapshot(resultado, gerado_em)
    finally:
        if not entregue:
            trava.liberar()


def obter_ou_calcular(
    chave_cache: str,
    calcular: Callable[[], Any],
    ttl_segundos: int = 300,
    reaproveitar: bool = True,
    guardar_se: Callable[[Any], bool] | None = None,
) -> Any:
    """`obter_snapshot` só com o dado (sem atualização em segundo plano nem
    snapshot velho): Dashboard e relatórios que não mostram a idade do dado."""

    return obter_snapshot(chave_cache, calcular, ttl_segundos, reaproveitar, guardar_se).data
