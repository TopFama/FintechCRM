"""Regras de negócio da cobrança via WhatsApp: cluster do cliente, faixa de
atraso e quem entra no WhatsApp. Vêm das planilhas da operação (clusterização
por valor pago, faixas de atraso e "clientes que entram na cobrança de
WhatsApp"); este módulo é a fonte única — extração, relatório e leads usam as
mesmas funções, sem repetir limite nenhum em SQL ou na tela.

Tudo aqui é puro (sem banco): dá para testar só com números.
"""

from dataclasses import dataclass
from decimal import Decimal

# Cliente que aparece nos filtros das duas planilhas de regra ("codigo não é
# 00384572"): fica fora de qualquer cobrança.
CODIGO_CLIENTE_IGNORADO = "00384572"

# --- Cluster: soma paga em títulos de venda -------------------------------

# (nome, valor pago mínimo — inclusive). O máximo de cada um é o mínimo do
# próximo. A planilha diz "<7000" para BEST SELLER e ">7000" para HEAVY USER,
# deixando 7000 exato sem dono; ele fica com HEAVY USER.
CLUSTERS: list[tuple[str, Decimal]] = [
    ("ESPECIAL", Decimal(0)),
    ("POTENCIAL", Decimal(400)),
    ("EM POTENCIAL", Decimal(1000)),
    ("ALTO POTENCIAL", Decimal(1500)),
    ("BEST SELLER", Decimal(3000)),
    ("HEAVY USER", Decimal(7000)),
]
NOMES_CLUSTER = [nome for nome, _ in CLUSTERS]


def cluster_por_valor_pago(valor_pago: Decimal | int | float | None) -> str:
    """Quem nunca pagou nada em venda (None ou 0) é ESPECIAL, o cluster de base."""

    valor = Decimal(str(valor_pago)) if valor_pago is not None else Decimal(0)
    escolhido = CLUSTERS[0][0]
    for nome, minimo in CLUSTERS:
        if valor >= minimo:
            escolhido = nome
    return escolhido


# --- Faixa de atraso -------------------------------------------------------

# (nome, dia_min, dia_max). Dias de atraso = hoje − vencimento da parcela em
# aberto mais antiga do cliente; negativo = ainda não venceu. Os nomes são o
# rótulo da planilha, e "primeiro dia" da faixa é o dia_min.
#
# "-1" e "2" são lidos pelo primeiro número do rótulo, como as demais faixas:
# "-1" cobre de -1 a 1 (vence amanhã, hoje ou venceu ontem) e "2" é só o dia 2.
# Quem está a 2+ dias de vencer (dias <= -2) não cai em faixa nenhuma.
FAIXAS: list[tuple[str, int, int | None]] = [
    ("-1", -1, 1),
    ("2", 2, 2),
    ("3 A 10", 3, 10),
    ("11 A 20", 11, 20),
    ("21 A 30", 21, 30),
    ("31 A 40", 31, 40),
    ("41 A 60", 41, 60),
    ("61 A 80", 61, 80),
    ("81 A 100", 81, 100),
    ("101 A 120", 101, 120),
    ("121 A 140", 121, 140),
    ("141 A 150", 141, 150),
    ("151+", 151, None),
]
NOMES_FAIXA = [nome for nome, _, _ in FAIXAS]
_FAIXA_POR_NOME = {nome: (dmin, dmax) for nome, dmin, dmax in FAIXAS}


def faixa_por_dias(dias_atraso: int) -> str | None:
    for nome, dmin, dmax in FAIXAS:
        if dias_atraso >= dmin and (dmax is None or dias_atraso <= dmax):
            return nome
    return None


def primeiro_dia_da_faixa(faixa: str) -> int:
    return _FAIXA_POR_NOME[faixa][0]


def eh_primeiro_dia(dias_atraso: int) -> bool:
    """Verdadeiro se o cliente está exatamente no primeiro dia da faixa dele
    (ex.: 21 dias na faixa "21 A 30")."""

    faixa = faixa_por_dias(dias_atraso)
    return faixa is not None and dias_atraso == primeiro_dia_da_faixa(faixa)


# --- Quem entra no WhatsApp: cluster × faixa -------------------------------

_BASE_ALTO = ["-1", "11 A 20", "31 A 40", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]
_BASE_POTENCIAL = ["-1", "2", "11 A 20", "31 A 40", "61 A 80", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]

# Faixas "3 A 10" e "41 A 60" não recebem WhatsApp em nenhum cluster.
FAIXAS_WHATSAPP: dict[str, frozenset[str]] = {
    "ESPECIAL": frozenset(["-1", "2", "11 A 20", "21 A 30", "61 A 80", "101 A 120", "121 A 140", "141 A 150", "151+"]),
    "POTENCIAL": frozenset(_BASE_POTENCIAL),
    "EM POTENCIAL": frozenset(_BASE_POTENCIAL),
    "ALTO POTENCIAL": frozenset(_BASE_ALTO),
    "BEST SELLER": frozenset(_BASE_ALTO),
    "HEAVY USER": frozenset(_BASE_ALTO),
}


def entra_no_whatsapp(cluster: str, faixa: str | None) -> bool:
    return faixa is not None and faixa in FAIXAS_WHATSAPP.get(cluster, frozenset())


# --- Faixa de compra: quantidade de compras no crediário ---------------------

NOMES_FAIXA_COMPRA = [str(n) for n in range(1, 10)] + ["10+"]


def faixa_de_compra(qtd_compras: int) -> str | None:
    """1 a 9 compras, depois "10+". Quem não tem nenhuma compra de crediário
    validada (ex.: só tem parcelas de reparcelamento) fica sem faixa (None)."""

    if qtd_compras < 1:
        return None
    return str(qtd_compras) if qtd_compras < 10 else "10+"


# --- Valor a cobrar no template do WhatsApp ----------------------------------


@dataclass(frozen=True)
class ParametrosJuros:
    """Parcela a parcela: com `dias_min` ou mais de atraso, o valor cobrado é
    valor + valor × juros_dia × dias + valor × multa; abaixo disso, só o valor.
    O juros mensal é rateado em 30 dias (15,99% a.m. → 0,533% ao dia)."""

    juros_mes_percentual: Decimal = Decimal("15.99")
    multa_percentual: Decimal = Decimal("2")
    dias_min: int = 3

    @property
    def juros_dia(self) -> Decimal:
        return self.juros_mes_percentual / Decimal(100) / Decimal(30)

    @property
    def multa(self) -> Decimal:
        return self.multa_percentual / Decimal(100)


PARAMETROS_JUROS_PADRAO = ParametrosJuros()
