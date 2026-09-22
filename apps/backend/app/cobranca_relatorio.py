"""Relatórios cluster × faixa de atraso sobre a base de cobrança."""

from .cobranca_regras import Regras


def montar_matriz(clientes: list[dict], regras: Regras, *, apenas_com_restricao_spc: bool = False) -> dict:
    """Conta clientes por cluster (linhas) e faixa de atraso (colunas), com os
    totais. Com `apenas_com_restricao_spc`, só conta quem tem restrição "sim"."""

    nomes_cluster = regras.nomes_cluster
    nomes_faixa = regras.nomes_faixa
    celulas = {c: {f: 0 for f in nomes_faixa} for c in nomes_cluster}
    for cliente in clientes:
        if cliente["faixa"] is None:
            continue
        if apenas_com_restricao_spc and cliente["spc_restricao"] != "sim":
            continue
        # cluster/faixa que não existem mais na matriz não estouram KeyError
        if cliente["cluster"] not in celulas:
            continue
        if cliente["faixa"] not in celulas[cliente["cluster"]]:
            continue
        celulas[cliente["cluster"]][cliente["faixa"]] += 1

    total_por_cluster = {c: sum(celulas[c].values()) for c in nomes_cluster}
    total_por_faixa = {f: sum(celulas[c][f] for c in nomes_cluster) for f in nomes_faixa}
    return {
        "celulas": celulas,
        "total_por_cluster": total_por_cluster,
        "total_por_faixa": total_por_faixa,
        "total": sum(total_por_cluster.values()),
    }
