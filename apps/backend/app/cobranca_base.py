"""Monta a base de clientes para cobrança: busca no SETA (`seta_client`) e
aplica as regras de `cobranca_regras` (cluster, faixa de atraso, matriz
WhatsApp, primeiro dia da faixa). Relatório, listagem e leads usam esta
mesma função, então todos enxergam exatamente os mesmos clientes."""

from datetime import date

from sqlalchemy.orm import Session

from . import seta_client
from .cobranca_regras import NOMES_FAIXA_COMPRA, faixa_de_compra
from .regras_db import carregar_regras
from .routers.blacklist import codigos_bloqueados
from .utils.phone import escolher_telefone


class FiltroInvalido(ValueError):
    """Nome de faixa/cluster desconhecido; a mensagem é segura para o usuário."""


def _validar(valores: list[str] | None, validos: list[str], rotulo: str) -> None:
    for v in valores or []:
        if v not in validos:
            raise FiltroInvalido(f"{rotulo} {v!r} não existe (use {', '.join(validos)})")


def buscar_base(
    db: Session,
    *,
    apenas_primeiro_dia: bool = True,
    somente_regra_whatsapp: bool = True,
    faixas: list[str] | None = None,
    clusters: list[str] | None = None,
    faixas_compra: list[str] | None = None,
    lojas: list[str] | None = None,
    portadores: list[str] | None = None,
    status_cliente: list[str] | None = None,
    vencimento_de: date | None = None,
    vencimento_ate: date | None = None,
    restricoes_spc: list[str] | None = None,
) -> list[dict]:
    """Clientes da base de cobrança, do mais atrasado para o menos.

    - `apenas_primeiro_dia`: traz só quem está exatamente no primeiro dia da
      faixa (ex.: faixa "21 A 30" → só clientes com 21 dias). Desligado, traz
      todos os dias da faixa.
    - `somente_regra_whatsapp`: aplica a matriz cluster × faixa da operação.
      Desligado, devolve todos (cada linha carrega `entra_whatsapp`).
    - `faixas` / `clusters`: restringem a essas faixas/clusters.
    - `faixas_compra`: restringe pela quantidade de compras no crediário (1 a 9, 10+).
    - `vencimento_de` / `vencimento_ate`: período do vencimento da parcela mais antiga.
    - `restricoes_spc`: "sim", "nao" e/ou "indeterminado".
    """

    if lojas is not None and not lojas:
        return []  # os atributos de loja escolhidos não casaram com nenhuma loja

    regras = carregar_regras(db)

    _validar(faixas, regras.nomes_faixa, "Faixa")
    _validar(clusters, regras.nomes_cluster, "Cluster")
    _validar(faixas_compra, NOMES_FAIXA_COMPRA, "Faixa de compra")
    _validar(restricoes_spc, ["sim", "nao", "indeterminado"], "Restrição SPC")

    if faixas:
        faixas_sel = list(faixas)
    elif somente_regra_whatsapp:
        # só as faixas em que algum dos clusters pedidos recebe WhatsApp
        dos_clusters = clusters or regras.nomes_cluster
        faixas_sel = [f for f in regras.nomes_faixa if any(regras.entra_no_whatsapp(c, f) for c in dos_clusters)]
    else:
        faixas_sel = list(regras.nomes_faixa)

    intervalos = [(regras.faixa(f).dia_min, regras.faixa(f).dia_max) for f in faixas_sel]
    dias_exatos = [regras.faixa(f).dia_min for f in faixas_sel] if apenas_primeiro_dia else None

    bl_codigos, bl_cpfs = codigos_bloqueados(db)
    linhas = seta_client.buscar_base_cobranca(
        faixas=intervalos,
        dias_exatos=dias_exatos,
        lojas=lojas,
        portadores=portadores,
        status_cliente=status_cliente,
        vencimento_de=vencimento_de,
        vencimento_ate=vencimento_ate,
        bloqueados_codigos=bl_codigos,
        bloqueados_cpfs=bl_cpfs,
        juros=regras.juros,
    )

    resultado = []
    for r in linhas:
        faixa = regras.faixa_por_dias(r["dias_atraso"])
        cluster = regras.cluster_por_valor_pago(r["valor_pago"])
        entra = regras.entra_no_whatsapp(cluster, faixa)
        compra = faixa_de_compra(r["qtd_compras"])
        if clusters and cluster not in clusters:
            continue
        if faixas_compra and compra not in faixas_compra:
            continue
        if restricoes_spc and r["spc_restricao"] not in restricoes_spc:
            continue
        if somente_regra_whatsapp and not entra:
            continue
        resultado.append(_montar_cliente(r, faixa, cluster, entra, compra))

    resultado.sort(key=lambda c: (-c["dias_atraso"], -c["valor_em_aberto"], c["codigo"]))
    return resultado


def _montar_cliente(r: dict, faixa: str | None, cluster: str, entra: bool, faixa_compra: str | None) -> dict:
    celular, origem = escolher_telefone(telefone2=r["telefone2"], telefone1=r["telefone1"], telefone3=r["telefone3"])
    # Para relatório de telefone inválido: o primeiro campo que tinha algum dígito.
    celular_original = next(
        (r[c] for c in ("telefone2", "telefone1", "telefone3") if r[c] and any(ch.isdigit() for ch in r[c])),
        None,
    )
    return {
        "codigo": r["codigo"],
        "nome": r["nome"],
        "celular": celular,
        "celular_origem": origem,
        "celular_original": celular_original,
        "cpfcnpj": "".join(ch for ch in (r["cpfcnpj"] or "") if ch.isdigit()) or None,
        "status": r["status"],
        "status_descricao": seta_client.STATUS_CLIENTE.get(r["status"], r["status"]),
        "loja_cadastro": r["loja_cadastro"] or None,
        "salario": r["salario"],
        "limite_rotativo": r["limite_rotativo"],
        "nascimento": r["nascimento"],
        "cadastro": r["cadastro"],
        "cluster": cluster,
        "valor_pago": r["valor_pago"],
        "qtd_compras": r["qtd_compras"],
        "faixa_compra": faixa_compra,
        "ultima_compra": r["ultima_compra"],
        "spc_restricao": r["spc_restricao"],
        "faixa": faixa,
        "dias_atraso": r["dias_atraso"],
        "entra_whatsapp": entra,
        "qtd_titulos": r["qtd_titulos"],
        "valor_em_aberto": r["valor_em_aberto"],
        "qtd_parcelas_cobranca": r["qtd_parcelas_cobranca"],
        "valor_cobrar": r["valor_cobrar"],
        "vencimento_mais_antigo": r["vencimento_mais_antigo"],
        "lojas": r["lojas"].split(",") if r["lojas"] else [],
        "portadores": r["portadores"].split(",") if r["portadores"] else [],
    }
