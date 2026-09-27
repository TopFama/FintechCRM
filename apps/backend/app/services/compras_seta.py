"""Cópia local das compras no crediário de cada cliente (faixa de compra).

Contar compras na base de cobrança fazia o SETA ler as vendas de ~146 mil
clientes a cada cálculo. Agora a contagem fica em `compras_seta`:
- toda madrugada, relê quem teve venda desde a última atualização;
- aos domingos, relê todos (pega cancelamento de venda antiga);
- ao abrir o filtro de faixa de compra, relê as vendas do dia (no máximo
  uma vez por minuto);
- cliente que ainda não está na cópia é lido na hora e guardado.
"""

import logging
import threading
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .. import models, seta_client
from ..timezone import BUSINESS_TZ, agora_br, hoje_br

logger = logging.getLogger("compras_seta")

SINCRONIZACAO = "compras"
LOTE = 5000
INTERVALO_MINIMO_SEGUNDOS = 60  # ao abrir o filtro: cliques seguidos não vão ao SETA de novo

_trava = threading.Lock()


def _em_lotes(itens: list, tamanho: int = LOTE):
    for i in range(0, len(itens), tamanho):
        yield itens[i : i + tamanho]


def _gravar(db: Session, compras: dict[str, tuple[int, date | None]]) -> None:
    agora = datetime.utcnow()
    for lote in _em_lotes(sorted(compras)):
        existentes = {
            c.codigo_cliente: c
            for c in db.query(models.CompraSeta).filter(models.CompraSeta.codigo_cliente.in_(lote))
        }
        for codigo in lote:
            qtd, ultima = compras[codigo]
            registro = existentes.get(codigo)
            if registro is None:
                db.add(models.CompraSeta(codigo_cliente=codigo, qtd_compras=qtd, ultima_compra=ultima, atualizado_em=agora))
            else:
                registro.qtd_compras, registro.ultima_compra, registro.atualizado_em = qtd, ultima, agora
    db.commit()


def _marcar(db: Session, quando: datetime) -> None:
    registro = db.get(models.SincronizacaoSeta, SINCRONIZACAO)
    if registro is None:
        db.add(models.SincronizacaoSeta(nome=SINCRONIZACAO, executado_em=quando))
    else:
        registro.executado_em = quando
    db.commit()


def obter(db: Session, codigos: list[str]) -> dict[str, tuple[int, date | None]]:
    """Código → (quantidade de compras, última compra). Quem ainda não está na
    cópia é lido no SETA agora e guardado. Com o SETA fora, fica com 0."""

    resultado: dict[str, tuple[int, date | None]] = {}
    for lote in _em_lotes(sorted(set(codigos))):
        for codigo, qtd, ultima in db.query(
            models.CompraSeta.codigo_cliente, models.CompraSeta.qtd_compras, models.CompraSeta.ultima_compra
        ).filter(models.CompraSeta.codigo_cliente.in_(lote)):
            resultado[codigo] = (qtd, ultima)
    faltam = sorted(set(codigos) - set(resultado))
    if faltam:
        try:
            novos = seta_client.compras_de_clientes(faltam)
        except seta_client.SetaIndisponivel:
            logger.warning("SETA fora: %d cliente(s) sem compras copiadas ficam com 0", len(faltam))
            return {**{c: (0, None) for c in faltam}, **resultado}
        with _trava:
            _gravar(db, novos)
        resultado.update(novos)
    return resultado


def atualizar_incremental(db: Session, forcar: bool = True) -> int:
    """Relê no SETA quem teve venda desde a data da última atualização (ou de
    hoje, se nunca rodou). `forcar=False` (tela) respeita o intervalo mínimo.
    Devolve quantos clientes foram relidos."""

    with _trava:
        registro = db.get(models.SincronizacaoSeta, SINCRONIZACAO)
        agora = datetime.utcnow()
        if (
            not forcar
            and registro is not None
            and (agora - registro.executado_em).total_seconds() < INTERVALO_MINIMO_SEGUNDOS
        ):
            return 0
        desde = hoje_br() if registro is None else min(hoje_br(), _dia_br(registro.executado_em))
        t0 = time.monotonic()
        codigos = seta_client.clientes_com_venda_desde(desde)
        compras = seta_client.compras_de_clientes(codigos)
        _gravar(db, compras)
        _marcar(db, agora)
        logger.info(
            "Compras do SETA (incremental desde %s): %d cliente(s) relidos em %.1f s", desde, len(codigos), time.monotonic() - t0
        )
        return len(codigos)


def carga_completa(db: Session) -> int:
    """Relê as compras de todos os clientes (domingo de madrugada). Quem está na
    cópia e não tem mais compra (venda cancelada) volta a 0."""

    with _trava:
        agora = datetime.utcnow()
        t0 = time.monotonic()
        compras = seta_client.compras_de_todos()
        sem_compra = {c for (c,) in db.query(models.CompraSeta.codigo_cliente)} - set(compras)
        compras.update({c: (0, None) for c in sem_compra})
        _gravar(db, compras)
        _marcar(db, agora)
        logger.info("Compras do SETA (carga completa): %d cliente(s) em %.1f s", len(compras), time.monotonic() - t0)
        return len(compras)


def _dia_br(dt: datetime) -> date:
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ).date()


def rodada_da_madrugada(db: Session) -> None:
    """Domingo: carga completa; demais dias: incremental."""
    if agora_br().weekday() == 6:
        carga_completa(db)
    else:
        atualizar_incremental(db)
