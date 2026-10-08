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


# --- Valor a cobrar no template do WhatsApp ----------------------------------


@dataclass(frozen=True)
class ParametrosJuros:
    """Parcela a parcela: com mais de `dias_min` dias de atraso (carência), o valor cobrado é
    valor + valor × juros_dia × dias + valor × multa; abaixo disso, só o valor.
    O juros mensal é rateado em 30 dias (15,99% a.m. → 0,533% ao dia)."""

    juros_mes_percentual: Decimal = Decimal("15.99")
    multa_percentual: Decimal = Decimal("2")
    dias_min: int = 2

    @property
    def juros_dia(self) -> Decimal:
        return self.juros_mes_percentual / Decimal(100) / Decimal(30)

    @property
    def multa(self) -> Decimal:
        return self.multa_percentual / Decimal(100)


PARAMETROS_JUROS_PADRAO = ParametrosJuros()


# --- Dataclasses das regras configuráveis -----------------------------------


@dataclass(frozen=True)
class Cluster:
    """Segmento do cliente pela soma paga em vendas.
    Vale de valor_min (inclusive) até o mínimo do próximo cluster."""

    nome: str
    valor_min: Decimal


@dataclass(frozen=True)
class FaixaAtraso:
    """Intervalo de dias de atraso. dia_max None = sem limite superior.
    'Primeiro dia' da faixa é sempre dia_min. `so_campanhas` (ex.: "Antecipado",
    antes do vencimento): só entra numa campanha que pede a faixa, nunca na
    matriz do WhatsApp nem no "todas as faixas"."""

    nome: str
    dia_min: int
    dia_max: int | None
    so_campanhas: bool = False


@dataclass(frozen=True)
class Regras:
    """Conjunto completo de regras de cobrança carregadas (do banco ou do padrão)."""

    clusters: tuple[Cluster, ...]          # ordenados por valor_min crescente
    faixas: tuple[FaixaAtraso, ...]        # ordenadas por dia_min crescente
    whatsapp: frozenset[tuple[str, str]]   # pares (nome_cluster, nome_faixa) que recebem WhatsApp
    juros: ParametrosJuros

    @property
    def nomes_faixa_regua(self) -> list[str]:
        """Faixas sem as só de campanhas: o "todas as faixas" de quem não pede uma."""
        return [f.nome for f in self.faixas if not f.so_campanhas]

    @property
    def nomes_faixa_so_campanhas(self) -> list[str]:
        return [f.nome for f in self.faixas if f.so_campanhas]

    @property
    def nomes_cluster(self) -> list[str]:
        return [c.nome for c in self.clusters]

    @property
    def nomes_faixa(self) -> list[str]:
        return [f.nome for f in self.faixas]

    def cluster_por_valor_pago(self, valor_pago: Decimal | int | float | None) -> str:
        """None ou 0 → cluster de menor valor_min (ESPECIAL). Usa o último
        cluster cujo valor_min <= valor."""
        valor = Decimal(str(valor_pago)) if valor_pago is not None else Decimal(0)
        escolhido = self.clusters[0].nome
        for c in self.clusters:
            if valor >= c.valor_min:
                escolhido = c.nome
        return escolhido

    def faixa_por_dias(self, dias_atraso: int) -> str | None:
        """Primeira faixa que contém o dia; None se nenhuma."""
        for f in self.faixas:
            if dias_atraso >= f.dia_min and (f.dia_max is None or dias_atraso <= f.dia_max):
                return f.nome
        return None

    def faixa(self, nome: str) -> FaixaAtraso:
        for f in self.faixas:
            if f.nome == nome:
                return f
        raise KeyError(f"Faixa {nome!r} não encontrada")

    def entra_no_whatsapp(self, cluster: str, faixa: str | None) -> bool:
        """False se faixa is None ou só de campanhas."""
        return faixa is not None and faixa not in self.nomes_faixa_so_campanhas and (cluster, faixa) in self.whatsapp

    def faixas_whatsapp(self, cluster: str) -> list[str]:
        """Nomes das faixas que recebem WhatsApp para o cluster, na ordem das faixas."""
        return [f.nome for f in self.faixas if self.entra_no_whatsapp(cluster, f.nome)]


# --- Faixa de compra: quantidade de compras no crediário (não configurável) ---

NOMES_FAIXA_COMPRA = [str(n) for n in range(1, 10)] + ["10+"]


def faixa_de_compra(qtd_compras: int) -> str | None:
    """1 a 9 compras, depois "10+". Quem não tem nenhuma compra de crediário
    validada (ex.: só tem parcelas de reparcelamento) fica sem faixa (None)."""

    if qtd_compras < 1:
        return None
    return str(qtd_compras) if qtd_compras < 10 else "10+"


# --- Valores padrão (seed) — reproduzem exatamente o comportamento atual ----

_CLUSTERS_PADRAO = (
    Cluster("ESPECIAL", Decimal(0)),
    Cluster("POTENCIAL", Decimal(400)),
    Cluster("EM POTENCIAL", Decimal(1000)),
    Cluster("ALTO POTENCIAL", Decimal(1500)),
    Cluster("BEST SELLER", Decimal(3000)),
    Cluster("HEAVY USER", Decimal(7000)),
)

_FAIXAS_PADRAO = (
    FaixaAtraso("-1", -1, 1),
    FaixaAtraso("2", 2, 2),
    FaixaAtraso("3 A 10", 3, 10),
    FaixaAtraso("11 A 20", 11, 20),
    FaixaAtraso("21 A 30", 21, 30),
    FaixaAtraso("31 A 40", 31, 40),
    FaixaAtraso("41 A 60", 41, 60),
    FaixaAtraso("61 A 80", 61, 80),
    FaixaAtraso("81 A 100", 81, 100),
    FaixaAtraso("101 A 120", 101, 120),
    FaixaAtraso("121 A 140", 121, 140),
    FaixaAtraso("141 A 150", 141, 150),
    FaixaAtraso("151+", 151, None),
)

_BASE_ALTO = ["-1", "11 A 20", "31 A 40", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]
_BASE_POTENCIAL = ["-1", "2", "11 A 20", "31 A 40", "61 A 80", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]

_WHATSAPP_PADRAO: frozenset[tuple[str, str]] = frozenset(
    [(c, f) for c in ["ESPECIAL"] for f in ["-1", "2", "11 A 20", "21 A 30", "61 A 80", "101 A 120", "121 A 140", "141 A 150", "151+"]]
    + [(c, f) for c in ["POTENCIAL", "EM POTENCIAL"] for f in _BASE_POTENCIAL]
    + [(c, f) for c in ["ALTO POTENCIAL", "BEST SELLER", "HEAVY USER"] for f in _BASE_ALTO]
)

REGRAS_PADRAO = Regras(
    clusters=_CLUSTERS_PADRAO,
    faixas=_FAIXAS_PADRAO,
    whatsapp=_WHATSAPP_PADRAO,
    juros=ParametrosJuros(),
)
