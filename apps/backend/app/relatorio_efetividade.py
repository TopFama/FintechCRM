"""Módulo de agregação do relatório de efetividade da cobrança.

Puro e sem banco: recebe as parcelas cobradas e a situação de liquidação e
calcula as métricas por faixa de atraso, por loja e o total consolidado.
"""

from decimal import Decimal
from typing import Sequence

from .cobranca_regras import REGRAS_PADRAO


def _calcular_metricas(itens_grupo: list[dict]) -> dict:
    if not itens_grupo:
        return {
            "qtd_envios": 0,
            "clientes_cobrados": 0,
            "valor_cobrado": Decimal("0.00"),
            "clientes_pagaram": 0,
            "valor_pago": Decimal("0.00"),
            "parcelas_cobradas": 0,
            "parcelas_pagas": 0,
            "parcelas_renegociadas": 0,
            "conversao_clientes": Decimal("0.0000"),
            "recuperacao_valor": Decimal("0.0000"),
        }

    clientes_cobrados_set = {it["codigo_cliente"] for it in itens_grupo}
    clientes_pagaram_set = {it["codigo_cliente"] for it in itens_grupo if it.get("pago")}
    envios_set = {it["lead_id"] for it in itens_grupo if it.get("lead_id")}

    clientes_cobrados = len(clientes_cobrados_set)
    clientes_pagaram = len(clientes_pagaram_set)
    # QTD DE ENVIOS: mensagens de WhatsApp mandadas (1 por lead marcado
    # "cobrado") — pode ser maior que clientes_cobrados se o mesmo cliente
    # tiver sido cobrado mais de uma vez no período (leads diferentes).
    qtd_envios = len(envios_set) if envios_set else clientes_cobrados

    valor_cobrado = sum((Decimal(str(it["valor_cobrar"])) for it in itens_grupo), Decimal("0.00")).quantize(
        Decimal("0.01")
    )
    valor_pago = sum(
        (Decimal(str(it.get("valor_pago", 0))) for it in itens_grupo if it.get("pago")), Decimal("0.00")
    ).quantize(Decimal("0.01"))

    parcelas_cobradas = len(itens_grupo)
    parcelas_pagas = sum(1 for it in itens_grupo if it.get("pago"))
    parcelas_renegociadas = sum(1 for it in itens_grupo if it.get("renegociada"))

    if clientes_cobrados > 0:
        conversao_clientes = (Decimal(clientes_pagaram) / Decimal(clientes_cobrados)).quantize(Decimal("0.0001"))
    else:
        conversao_clientes = Decimal("0.0000")

    if valor_cobrado > Decimal("0.00"):
        recuperacao_valor = (Decimal(valor_pago) / Decimal(valor_cobrado)).quantize(Decimal("0.0001"))
    else:
        recuperacao_valor = Decimal("0.0000")

    return {
        "qtd_envios": qtd_envios,
        "clientes_cobrados": clientes_cobrados,
        "valor_cobrado": valor_cobrado,
        "clientes_pagaram": clientes_pagaram,
        "valor_pago": valor_pago,
        "parcelas_cobradas": parcelas_cobradas,
        "parcelas_pagas": parcelas_pagas,
        "parcelas_renegociadas": parcelas_renegociadas,
        "conversao_clientes": conversao_clientes,
        "recuperacao_valor": recuperacao_valor,
    }


def montar_relatorio(
    itens: list[dict],
    *,
    lojas_info: dict[str, dict] | None = None,
    faixas_ordem: Sequence[str] | None = None,
) -> dict:
    """Consolida os dados de efetividade por faixa de atraso, por loja e total.

    - itens: lista de parcelas cobradas, com codigo_cliente, faixa, empresa,
      valor_cobrar, pago, renegociada, valor_pago.
    - lojas_info: mapa filial -> {nome_com_cod, regional, cluster_inad}.
    - faixas_ordem: sequência de nomes de faixa para ordenação de por_faixa.
    """
    lojas_info = lojas_info or {}
    ordem_referencia = faixas_ordem if faixas_ordem is not None else REGRAS_PADRAO.nomes_faixa
    ordem_map = {nome: i for i, nome in enumerate(ordem_referencia)}

    def _sort_faixa(faixa: str):
        return (ordem_map.get(faixa, 9999), faixa)

    faixas_map: dict[str, list[dict]] = {}
    lojas_map: dict[str, list[dict]] = {}

    for it in itens:
        faixas_map.setdefault(it["faixa"], []).append(it)
        lojas_map.setdefault(it["empresa"], []).append(it)

    por_faixa = []
    for f in sorted(faixas_map.keys(), key=_sort_faixa):
        metricas = _calcular_metricas(faixas_map[f])
        por_faixa.append({"faixa": f, **metricas})

    por_loja = []
    for l in sorted(lojas_map.keys()):
        info = lojas_info.get(l)
        metricas = _calcular_metricas(lojas_map[l])
        por_loja.append(
            {
                "loja": l,
                "loja_nome": info.get("nome_com_cod") if info else None,
                "regional": info.get("regional") if info else None,
                "cluster_inad": info.get("cluster_inad") if info else None,
                **metricas,
            }
        )

    total = _calcular_metricas(itens)

    return {
        "por_faixa": por_faixa,
        "por_loja": por_loja,
        "total": total,
    }
