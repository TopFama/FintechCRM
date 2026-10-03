"""Números dos cards do Dashboard em tempo real (WebSocket /dashboard/ws).

O Postgres avisa no canal "painel" (triggers da migration a3d5f7b9c1e2) o
saldo de cada comando que mexe na fila, nos telefones inválidos ou nas pausas,
só no COMMIT, com o id da transação. Um ouvinte por instalação (trava no
Redis) é o único que escreve os contadores do dia (`painel:dia:<AAAA-MM-DD>`,
dia de Brasília): carrega o dia pela mesma contagem dos cards e relatórios
(`consultas_fila.contar_cards`) e soma os avisos que vierem depois, em ordem.
A carga guarda o snapshot do Postgres em que contou; aviso de transação que
já estava nesse snapshot não soma de novo (sem contar duas vezes nem perder
o commit que chega no meio da carga). Ao (re)conectar o ouvinte, todos os
dias são descartados e recarregados sob demanda (aviso perdido com o ouvinte
fora não fica).

O WebSocket só lê: dia ainda não carregado vira um pedido ao ouvinte (aviso
"carregar" no mesmo canal) e os números saem quando ele publica. Pausados não
é contador (pausa não muda o status do item): é recontado com cache curto,
renovado na hora a cada mudança de pausa.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import psycopg
from sqlalchemy import text
from sqlalchemy.engine import make_url

from . import cache, consultas_fila
from .config import settings
from .database import SessionLocal
from .timezone import hoje_br

logger = logging.getLogger(__name__)

CANAL = "painel"
DIAS_GUARDADOS = 35  # cobre "Este mês" e "Últimos 7 dias"; período mais antigo fica no polling
PAUSADOS_TTL_SEGUNDOS = 5  # mudança na fila aparece em Pausados em até isso; mudança de pausa, na hora
ESPERA_AVISOS_SEGUNDOS = 10  # de quanto em quanto o ouvinte renova a trava
SINAL_A_CADA_SEGUNDOS = 60  # pausa com data final vence sem gravar nada: as telas reconferem
TRAVA_TTL_SEGUNDOS = 30

_TRAVA = "lock:painel-ouvinte"
_VERSAO_PAUSAS = "painel:versao-pausas"
_CAMPO = {
    "pending": "total_pendentes",
    "reserved": "total_pendentes",
    "sent": "total_enviados",
    "error": "total_erros",
    "invalido": "total_telefones_invalidos",
}
_CAMPOS = sorted(set(_CAMPO.values()))
# só soma em dia carregado: dia que venceu no Redis não vira contador parcial
_LUA_SOMAR = "if redis.call('exists', KEYS[1]) == 1 then redis.call('hincrby', KEYS[1], ARGV[1], ARGV[2]) end return 0"

# Threads próprias: o WebSocket e o ouvinte não disputam o pool padrão do
# asyncio com o resto do backend (webhook do Chatwoot), nem um com o outro.
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="painel")
_executor_ouvinte = ThreadPoolExecutor(max_workers=1, thread_name_prefix="painel-ouvinte")

_contadores: Counter = Counter()
# Snapshot do Postgres em que cada dia foi carregado (só o ouvinte usa)
_cargas: dict[date, tuple[int, int, set[int]]] = {}


class Indisponivel(Exception):
    """Ouvinte parado (backend subindo, banco ou Redis fora): tentar de novo depois."""


def metricas() -> dict:
    """Avisos aplicados, cargas de dia e recomeços desde que o processo subiu."""
    return dict(_contadores)


def _chave(dia: date) -> str:
    return f"painel:dia:{dia.isoformat()}"


def _ler_snapshot(texto: str) -> tuple[int, int, set[int]]:
    xmin, xmax, ativos = texto.split(":")
    return int(xmin), int(xmax), {int(x) for x in ativos.split(",") if x}


def _ja_contada(xid: int, snapshot: tuple[int, int, set[int]]) -> bool:
    """A transação já tinha terminado quando o snapshot da carga foi tirado
    (mesma regra do pg_visible_in_snapshot)."""
    xmin, xmax, ativos = snapshot
    return xid < xmin or (xid < xmax and xid not in ativos)


def _carregar(dias: list[date]) -> None:
    """Conta os dias numa transação só (REPEATABLE READ) e guarda o snapshot dela."""

    with SessionLocal() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        snapshot = _ler_snapshot(db.execute(text("SELECT pg_current_snapshot()::text")).scalar())
        contagens = {dia: consultas_fila.contar_cards(db, dia, dia) for dia in dias}
    r = cache.redis_cliente()
    with r.pipeline() as p:
        for dia, numeros in contagens.items():
            p.delete(_chave(dia))
            p.hset(_chave(dia), mapping=numeros)
            p.expire(_chave(dia), DIAS_GUARDADOS * 86400)
        p.execute()
    for dia in dias:
        _cargas[dia] = snapshot
    _contadores["cargas"] += len(dias)


def _pedir_carga(dias: list[date]) -> None:
    with SessionLocal() as db:
        db.execute(text("SELECT pg_notify(:canal, :aviso)"), {"canal": CANAL, "aviso": json.dumps({"carregar": [d.isoformat() for d in dias]})})
        db.commit()


def numeros(de: date | None, ate: date | None) -> dict[str, int] | None:
    """Os cinco números dos cards no período; None se o período não é
    acompanhado em tempo real (sem datas ou mais antigo que DIAS_GUARDADOS).
    Dia ainda não carregado: pede ao ouvinte e devolve {} (os números saem
    quando ele publicar). Sem ouvinte, Indisponivel."""

    hoje = hoje_br()
    if de is None or ate is None or (hoje - de).days >= DIAS_GUARDADOS:
        return None
    r = cache.redis_cliente()
    if not r.exists(_TRAVA):
        raise Indisponivel
    dias = [de + timedelta(days=i) for i in range((min(ate, hoje) - de).days + 1)]
    with r.pipeline() as p:
        for dia in dias:
            p.hgetall(_chave(dia))
        guardados = p.execute()
    faltando = [dia for dia, guardado in zip(dias, guardados) if not guardado]
    if faltando:
        _pedir_carga(faltando)
        return {}
    totais: Counter = Counter()
    for guardado in guardados:
        totais.update({k: int(v) for k, v in guardado.items()})
    with SessionLocal() as db:
        pausados = cache.obter_ou_calcular(
            cache.chave("painel-pausados", {"de": de, "ate": ate, "versao": r.get(_VERSAO_PAUSAS)}),
            lambda: consultas_fila.contar_pausados(db, consultas_fila.periodo_dos_cards(de, ate)),
            PAUSADOS_TTL_SEGUNDOS,
        )
    return {**{campo: totais[campo] for campo in _CAMPOS}, "total_pausados": pausados}


def _hora(valor: str | None) -> datetime | None:
    return datetime.fromisoformat(valor) if valor else None


def aplicar(aviso: str) -> None:
    """Trata um aviso do Postgres (só o ouvinte, um de cada vez, na ordem dos commits)."""

    dados = json.loads(aviso)
    r = cache.redis_cliente()
    if "carregar" in dados:
        hoje = hoje_br()
        dias = [d for d in map(date.fromisoformat, dados["carregar"]) if not r.exists(_chave(d)) and d <= hoje]
        if dias:
            _carregar(dias)
    elif dados.get("recontar"):
        recomecar()
        return
    elif dados.get("pausas"):
        r.incr(_VERSAO_PAUSAS)
    else:
        xid = int(dados["x"])
        saldo: Counter = Counter()
        for d in dados["d"]:
            dia = consultas_fila.dia_do_card(d["s"], _hora(d["c"]), _hora(d["e"]))
            if dia in _cargas and d["s"] in _CAMPO and not _ja_contada(xid, _cargas[dia]):
                saldo[(dia, _CAMPO[d["s"]])] += d["n"]
        for (dia, campo), n in saldo.items():
            if n:
                r.eval(_LUA_SOMAR, 1, _chave(dia), campo, n)
        _contadores["avisos"] += 1
    r.publish(CANAL, "1")


def recomecar() -> None:
    """Descarta todos os dias (podem ter perdido avisos); as telas pedem de novo."""

    r = cache.redis_cliente()
    for chave in r.scan_iter("painel:dia:*"):
        r.delete(chave)
    _cargas.clear()
    r.incr(_VERSAO_PAUSAS)
    _contadores["recomecos"] += 1
    r.publish(CANAL, "1")


def _manter_trava(token: str, dono: bool) -> bool:
    """Trava sem prazo de vida (cache._Trava solta sozinha depois de 30 min):
    o ouvinte é dono enquanto renova; reconectando, retoma a própria trava."""

    r = cache.redis_cliente()
    if dono or not r.set(_TRAVA, token, nx=True, ex=TRAVA_TTL_SEGUNDOS):
        return bool(r.eval(cache.LUA_RENOVAR, 1, _TRAVA, token, TRAVA_TTL_SEGUNDOS))
    return True


async def ouvir() -> None:
    """Ouvinte dos avisos do Postgres; roda enquanto o backend vive (lifespan).
    Só o dono da trava aplica os avisos, para não somar duas vezes."""

    url = make_url(settings.database_url)
    if url.get_backend_name() != "postgresql":
        return
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    token = uuid.uuid4().hex
    loop = asyncio.get_running_loop()

    def em_thread(funcao, *args):
        return loop.run_in_executor(_executor_ouvinte, funcao, *args)

    while True:
        dono = False
        try:
            async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
                await conn.execute(f"LISTEN {CANAL}")
                proximo_sinal = time.monotonic() + SINAL_A_CADA_SEGUNDOS
                while True:
                    era_dono, dono = dono, await em_thread(_manter_trava, token, dono)
                    if dono and not era_dono:
                        # avisos de antes do LISTEN (ou de quando outro era dono) se perderam
                        await em_thread(recomecar)
                    elif dono and time.monotonic() >= proximo_sinal:
                        await em_thread(lambda: cache.redis_cliente().publish(CANAL, "1"))
                        proximo_sinal = time.monotonic() + SINAL_A_CADA_SEGUNDOS
                    async for aviso in conn.notifies(timeout=ESPERA_AVISOS_SEGUNDOS):
                        if dono:
                            await em_thread(aplicar, aviso.payload)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - banco ou Redis fora: o Dashboard fica no polling até voltar
            logger.warning("Painel em tempo real: ouvinte parado, tentando de novo em 10 s", exc_info=True)
            await asyncio.sleep(10)
