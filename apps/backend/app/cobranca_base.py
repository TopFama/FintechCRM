"""Monta a base de clientes para cobrança: busca no SETA (`seta_client`) e
aplica as regras de `cobranca_regras` (cluster, faixa de atraso, matriz
WhatsApp, primeiro dia da faixa). Relatório, listagem e leads usam esta
mesma função, então todos enxergam exatamente os mesmos clientes.

A consulta ao SETA (`seta_client.buscar_base_cobranca`) é a parte cara —
tabela de títulos com mais de 27M de linhas — e por isso passa pelo cache
Redis (`cache.py`): filtro igual a um pedido de minutos atrás sai do cache
na hora; filtro novo dispara o cálculo em segundo plano e devolve
"processing" (quem pediu tenta de novo em seguida, sem segurar a conexão
HTTP)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from . import cache, seta_client
from .services import compras_seta
from .cobranca_regras import NOMES_FAIXA_COMPRA, faixa_de_compra
from .regras_db import carregar_regras
from .timezone import hoje_br
from .blacklist import codigos_bloqueados
from .utils.phone import escolher_telefone, primeiro_telefone_preenchido


class FiltroInvalido(ValueError):
    """Nome de faixa/cluster desconhecido; a mensagem é segura para o usuário."""


def _validar(valores: list[str] | None, validos: list[str], rotulo: str) -> None:
    for v in valores or []:
        if v not in validos:
            raise FiltroInvalido(f"{rotulo} {v!r} não existe (use {', '.join(validos)})")


# Campos das linhas cruas do SETA que viram texto na ida ao Redis (Decimal e
# date não são JSON nativamente) e precisam ser restaurados na volta.
_CAMPOS_DECIMAL_SETA = (
    "salario", "limite_rotativo", "valor_pago", "valor_em_aberto", "valor_cobrar",
    "valor_atraso_original", "valor_atraso_juros",
)
_CAMPOS_DATA_SETA = ("nascimento", "cadastro", "ultima_compra", "vencimento_mais_antigo")


def _restaurar_linha_seta(linha: dict) -> dict:
    linha = dict(linha)
    for campo in _CAMPOS_DECIMAL_SETA:
        if linha.get(campo) is not None:
            linha[campo] = Decimal(str(linha[campo]))
    for campo in _CAMPOS_DATA_SETA:
        valor = linha.get(campo)
        if isinstance(valor, str):
            linha[campo] = date.fromisoformat(valor[:10])
    return linha


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
    valor_atraso_min: Decimal | None = None,
    valor_atraso_max: Decimal | None = None,
    valor_atraso_com_juros: bool = False,
    codigos: list[str] | None = None,
) -> dict:
    """{"status": "ready", "data": [...]} com os clientes da base de
    cobrança (do mais atrasado para o menos), ou {"status": "processing",
    "data": None} enquanto a consulta ao SETA calcula em segundo plano.

    - `apenas_primeiro_dia`: traz só quem está exatamente no primeiro dia da
      faixa (ex.: faixa "21 A 30" → só clientes com 21 dias). Desligado, traz
      todos os dias da faixa.
    - `somente_regra_whatsapp`: aplica a matriz cluster × faixa da operação.
      Desligado, devolve todos (cada linha carrega `entra_whatsapp`).
    - `faixas` / `clusters`: restringem a essas faixas/clusters.
    - `faixas_compra`: restringe pela quantidade de compras no crediário (1 a 9, 10+).
    - `vencimento_de` / `vencimento_ate`: período do vencimento da parcela mais antiga.
    - `restricoes_spc`: "sim", "nao" e/ou "indeterminado".
    - `valor_atraso_min` / `valor_atraso_max`: total das parcelas já vencidas,
      pelo valor original ou, com `valor_atraso_com_juros`, com multa e juros.
    - `codigos`: só esses clientes (planilha de clientes de uma campanha).
    """

    if (lojas is not None and not lojas) or (codigos is not None and not codigos):
        return {"status": "ready", "data": []}  # atributos de loja escolhidos não casaram com nenhuma loja

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

    chave_cache = cache.chave(
        "seta_base_cobranca",
        {
            # Dias de atraso e juros mudam na virada do dia: a base de ontem não serve hoje
            "dia": hoje_br(),
            "intervalos": intervalos,
            "dias_exatos": dias_exatos,
            "lojas": sorted(lojas) if lojas else None,
            "portadores": sorted(portadores) if portadores else None,
            "status_cliente": sorted(status_cliente) if status_cliente else None,
            "vencimento_de": vencimento_de,
            "vencimento_ate": vencimento_ate,
            "bl_codigos": sorted(bl_codigos),
            "bl_cpfs": sorted(bl_cpfs),
            "juros_mes_percentual": str(regras.juros.juros_mes_percentual),
            "multa_percentual": str(regras.juros.multa_percentual),
            "dias_min_juros": regras.juros.dias_min,
            "codigos": sorted(codigos) if codigos else None,
            # linhas com valor em atraso (sem e com juros); não reaproveita cache de antes
            # 3: linhas trazem telefone4 (quarta opção de celular)
            "versao": 3,
        },
    )

    def calcular_linhas() -> list[dict]:
        return seta_client.buscar_base_cobranca(
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
            codigos=sorted(codigos) if codigos else None,
        )

    job = cache.buscar_ou_iniciar(chave_cache, calcular_linhas)
    if job["status"] != "ready":
        return {"status": "processing", "data": None}

    # Faixa de compra vem da cópia local (fora do cache do SETA): depois de
    # atualizar as compras do dia, a lista já mostra a faixa nova.
    compras = compras_seta.obter(db, [linha["codigo"] for linha in job["data"]])

    resultado = []
    for linha_bruta in job["data"]:
        r = _restaurar_linha_seta(linha_bruta)
        r["qtd_compras"], r["ultima_compra"] = compras.get(r["codigo"], (0, None))
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
        if valor_atraso_min is not None or valor_atraso_max is not None:
            valor_atraso = r["valor_atraso_juros"] if valor_atraso_com_juros else r["valor_atraso_original"]
            if valor_atraso_min is not None and valor_atraso < valor_atraso_min:
                continue
            if valor_atraso_max is not None and valor_atraso > valor_atraso_max:
                continue
        resultado.append(_montar_cliente(r, faixa, cluster, entra, compra))

    resultado.sort(key=lambda c: (-c["dias_atraso"], -c["valor_em_aberto"], c["codigo"]))
    return {"status": "ready", "data": resultado}


def _montar_cliente(r: dict, faixa: str | None, cluster: str, entra: bool, faixa_compra: str | None) -> dict:
    celular, origem = escolher_telefone(r)
    # Para relatório de telefone inválido: o primeiro campo que tinha algum dígito.
    celular_original = primeiro_telefone_preenchido(r)
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
        "valor_atraso_original": r["valor_atraso_original"],
        "valor_atraso_juros": r["valor_atraso_juros"],
        "vencimento_mais_antigo": r["vencimento_mais_antigo"],
        "lojas": r["lojas"].split(",") if r["lojas"] else [],
        "portadores": r["portadores"].split(",") if r["portadores"] else [],
    }
