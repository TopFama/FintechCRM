"""Relatórios cluster × faixa de atraso sobre a base de cobrança."""

from .cobranca_regras import NOMES_CLUSTER, NOMES_FAIXA


def montar_matriz(clientes: list[dict], *, apenas_com_restricao_spc: bool = False) -> dict:
    """Conta clientes por cluster (linhas) e faixa de atraso (colunas), com os
    totais. Com `apenas_com_restricao_spc`, só conta quem tem restrição "sim"."""

    celulas = {c: {f: 0 for f in NOMES_FAIXA} for c in NOMES_CLUSTER}
    for cliente in clientes:
        if cliente["faixa"] is None:
            continue
        if apenas_com_restricao_spc and cliente["spc_restricao"] != "sim":
            continue
        celulas[cliente["cluster"]][cliente["faixa"]] += 1

    total_por_cluster = {c: sum(celulas[c].values()) for c in NOMES_CLUSTER}
    total_por_faixa = {f: sum(celulas[c][f] for c in NOMES_CLUSTER) for f in NOMES_FAIXA}
    return {
        "celulas": celulas,
        "total_por_cluster": total_por_cluster,
        "total_por_faixa": total_por_faixa,
        "total": sum(total_por_cluster.values()),
    }
