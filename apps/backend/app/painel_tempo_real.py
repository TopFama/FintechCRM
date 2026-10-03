"""Números dos cards do Dashboard em tempo real (WebSocket /dashboard/ws).

O Postgres avisa no canal "painel" (triggers da migration a3d5f7b9c1e2) o
saldo de cada comando que mexe na fila, nos telefones inválidos ou nas pausas,
só no COMMIT. Um ouvinte por instalação (trava no Redis) soma o saldo no
contador do dia (`painel:dia:<AAAA-MM-DD>`, dia de Brasília) e publica no
canal Redis "painel"; cada WebSocket soma os dias do seu período e envia.

O contador de um dia nasce da mesma contagem dos cards e dos relatórios
(`consultas_fila.contar_cards`) e é refeito a cada RECONTAR_A_CADA_SEGUNDOS
nos dias que alguém está vendo; ao (re)conectar o ouvinte, todos os dias são
descartados e refeitos sob demanda (aviso perdido com o backend fora não fica).
Pausados não é contador (pausa não muda o status do item): é recontado uma
vez por aviso e período, compartilhado entre as telas (cache pela versão).
"""

import asyncio
import json
import logging
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta

import psycopg
from sqlalchemy.engine import make_url

from . import cache, consultas_fila
from .config import settings
from .database import SessionLocal
from .timezone import hoje_br

logger = logging.getLogger(__name__)

CANAL = "painel"
DIAS_GUARDADOS = 35  # cobre "Este mês" e "Últimos 7 dias"; período mais antigo fica no polling
RECONTAR_A_CADA_SEGUNDOS = 60
PAUSADOS_TTL_SEGUNDOS = 60  # a chave muda a cada aviso; isto só limpa as antigas
EM_USO_SEGUNDOS = 120  # dia que nenhum WebSocket pediu nesse tempo deixa de ser recontado
ESPERA_AVISOS_SEGUNDOS = 10  # de quanto em quanto o ouvinte renova a trava
TRAVA_TTL_SEGUNDOS = 30

_TRAVA = "lock:painel-ouvinte"
_EM_USO = "painel:em-uso"
_VERSAO = "painel:versao"  # muda a cada aviso: Pausados é recontado na hora
_CAMPO = {
    "pending": "total_pendentes",
    "reserved": "total_pendentes",
    "sent": "total_enviados",
    "error": "total_erros",
    "invalido": "total_telefones_invalidos",
}
_CAMPOS = sorted(set(_CAMPO.values()))
# só soma em dia já carregado: dia que ninguém pediu não vira contador parcial
_LUA_SOMAR = "if redis.call('exists', KEYS[1]) == 1 then redis.call('hincrby', KEYS[1], ARGV[1], ARGV[2]) end return 0"

_contadores: Counter = Counter()


class Indisponivel(Exception):
    """Ouvinte parado (backend subindo, banco ou Redis fora): tentar de novo depois."""


def metricas() -> dict:
    """Avisos aplicados, recontagens e divergências desde que o processo subiu."""
    return dict(_contadores)


def _chave(dia: date) -> str:
    return f"painel:dia:{dia.isoformat()}"


def _gravar_dia(db, dia: date) -> dict[str, int]:
    numeros = consultas_fila.contar_cards(db, dia, dia)
    r = cache.redis_cliente()
    anterior = {k: int(v) for k, v in r.hgetall(_chave(dia)).items()}
    with r.pipeline() as p:
        p.delete(_chave(dia))
        p.hset(_chave(dia), mapping=numeros)
        p.expire(_chave(dia), DIAS_GUARDADOS * 86400)
        p.execute()
    if anterior and anterior != numeros:
        _contadores["divergencias"] += 1
        logger.warning("Painel: contador de %s corrigido pela recontagem (%s → %s)", dia, anterior, numeros)
    return numeros


def numeros(de: date | None, ate: date | None) -> dict[str, int] | None:
    """Os cinco números dos cards no período, ou None se o período não é
    acompanhado em tempo real (sem datas ou mais antigo que DIAS_GUARDADOS).
    Sem ouvinte, Indisponivel: o contador não acompanharia as mudanças."""

    hoje = hoje_br()
    if de is None or ate is None or (hoje - de).days >= DIAS_GUARDADOS:
        return None
    dias = [de + timedelta(days=i) for i in range((min(ate, hoje) - de).days + 1)]
    r = cache.redis_cliente()
    if not r.exists(_TRAVA):
        raise Indisponivel
    totais: Counter = Counter()
    with SessionLocal() as db:
        with r.pipeline() as p:
            for dia in dias:
                p.hgetall(_chave(dia))
            guardados = p.execute()
        for dia, guardado in zip(dias, guardados):
            totais.update({k: int(v) for k, v in guardado.items()} if guardado else _gravar_dia(db, dia))
        if dias:
            r.zadd(_EM_USO, {dia.isoformat(): time.time() for dia in dias})
        pausados = cache.obter_ou_calcular(
            cache.chave("painel-pausados", {"de": de, "ate": ate, "versao": r.get(_VERSAO)}),
            lambda: consultas_fila.contar_pausados(db, consultas_fila.periodo_dos_cards(de, ate)),
            PAUSADOS_TTL_SEGUNDOS,
        )
    return {**{campo: totais[campo] for campo in _CAMPOS}, "total_pausados": pausados}


def _hora(valor: str | None) -> datetime | None:
    return datetime.fromisoformat(valor) if valor else None


def aplicar(aviso: str) -> None:
    """Soma o saldo de um aviso do Postgres nos contadores e avisa os WebSockets."""

    dados = json.loads(aviso)
    r = cache.redis_cliente()
    if isinstance(dados, list):
        saldo: Counter = Counter()
        for d in dados:
            dia = consultas_fila.dia_do_card(d["s"], _hora(d["c"]), _hora(d["e"]))
            if dia and d["s"] in _CAMPO:
                saldo[(dia, _CAMPO[d["s"]])] += d["n"]
        for (dia, campo), n in saldo.items():
            if n:
                r.eval(_LUA_SOMAR, 1, _chave(dia), campo, n)
        _contadores["avisos"] += 1
    elif dados.get("recontar"):
        recomecar()
    _avisar(r)


def _avisar(r) -> None:
    r.incr(_VERSAO)
    r.publish(CANAL, "1")


def recontar() -> None:
    """Refaz pela contagem do banco os dias que alguém está vendo."""

    r = cache.redis_cliente()
    r.zremrangebyscore(_EM_USO, 0, time.time() - EM_USO_SEGUNDOS)
    with SessionLocal() as db:
        for dia in r.zrange(_EM_USO, 0, -1):
            _gravar_dia(db, date.fromisoformat(dia))
    _contadores["recontagens"] += 1
    _avisar(r)


def recomecar() -> None:
    """Descarta todos os dias (podem ter perdido avisos) e refaz os que estão em uso."""

    r = cache.redis_cliente()
    for chave in r.scan_iter("painel:dia:*"):
        r.delete(chave)
    recontar()


def _manter_trava(token: str, dono: bool) -> bool:
    r = cache.redis_cliente()
    if dono:
        return bool(r.eval(cache.LUA_RENOVAR, 1, _TRAVA, token, TRAVA_TTL_SEGUNDOS))
    return bool(r.set(_TRAVA, token, nx=True, ex=TRAVA_TTL_SEGUNDOS))


async def ouvir() -> None:
    """Ouvinte dos avisos do Postgres; roda enquanto o backend vive (lifespan).
    Só o dono da trava aplica os avisos, para não somar duas vezes."""

    url = make_url(settings.database_url)
    if url.get_backend_name() != "postgresql":
        return
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    token = uuid.uuid4().hex
    while True:
        dono = False
        try:
            async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
                await conn.execute(f"LISTEN {CANAL}")
                proxima_recontagem = time.monotonic() + RECONTAR_A_CADA_SEGUNDOS
                while True:
                    era_dono, dono = dono, await asyncio.to_thread(_manter_trava, token, dono)
                    if dono and not era_dono:
                        await asyncio.to_thread(recomecar)
                    elif dono and time.monotonic() >= proxima_recontagem:
                        await asyncio.to_thread(recontar)
                        proxima_recontagem = time.monotonic() + RECONTAR_A_CADA_SEGUNDOS
                    async for aviso in conn.notifies(timeout=ESPERA_AVISOS_SEGUNDOS):
                        if dono:
                            await asyncio.to_thread(aplicar, aviso.payload)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - banco ou Redis fora: o Dashboard fica no polling até voltar
            logger.warning("Painel em tempo real: ouvinte parado, tentando de novo em 10 s", exc_info=True)
            await asyncio.sleep(10)
