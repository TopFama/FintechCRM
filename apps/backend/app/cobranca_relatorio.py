"""Relatórios cluster × faixa de atraso sobre a base de cobrança."""

from decimal import Decimal
from typing import Any, Callable

from .cobranca_regras import Regras


def _montar_matriz_generica(
    clientes: list[dict],
    regras: Regras,
    valor_fn: Callable[[dict], Any],
    zero: Any,
    *,
    apenas_com_restricao_spc: bool = False,
) -> dict:
    nomes_cluster = regras.nomes_cluster
    nomes_faixa = regras.nomes_faixa
    celulas = {c: {f: zero for f in nomes_faixa} for c in nomes_cluster}
    for cliente in clientes:
        if cliente.get("faixa") is None:
            continue
        if apenas_com_restricao_spc and cliente.get("spc_restricao") != "sim":
            continue
        cluster = cliente.get("cluster")
        faixa = cliente.get("faixa")
        if cluster not in celulas:
            continue
        if faixa not in celulas[cluster]:
            continue
        celulas[cluster][faixa] += valor_fn(cliente)

    total_por_cluster = {c: sum(celulas[c].values(), zero) for c in nomes_cluster}
    total_por_faixa = {f: sum((celulas[c][f] for c in nomes_cluster), zero) for f in nomes_faixa}
    return {
        "celulas": celulas,
        "total_por_cluster": total_por_cluster,
        "total_por_faixa": total_por_faixa,
        "total": sum(total_por_cluster.values(), zero),
    }


def montar_matriz(clientes: list[dict], regras: Regras, *, apenas_com_restricao_spc: bool = False) -> dict:
    """Conta clientes por cluster (linhas) e faixa de atraso (colunas), com os
    totais. Com `apenas_com_restricao_spc`, só conta quem tem restrição "sim"."""
    return _montar_matriz_generica(
        clientes,
        regras,
        valor_fn=lambda _c: 1,
        zero=0,
        apenas_com_restricao_spc=apenas_com_restricao_spc,
    )


def montar_matriz_valor(
    clientes: list[dict],
    regras: Regras,
    *,
    campo: str = "valor_em_aberto",
    apenas_com_restricao_spc: bool = False,
) -> dict:
    """Soma um valor dos clientes (padrão: valor em aberto) por cluster
    (linhas) e faixa de atraso (colunas), com os totais."""
    return _montar_matriz_generica(
        clientes,
        regras,
        valor_fn=lambda c: Decimal(str(c.get(campo) or 0)),
        zero=Decimal("0"),
        apenas_com_restricao_spc=apenas_com_restricao_spc,
    )

