"""Leitura do texto da consulta SPC guardado em `pessoas.scpcresultado` no SETA.

O campo é o retorno bruto da consulta, algo como:

    RESTRIÇÃO     : NÃO
    PROTOCOLO     : 15009454867-1    DATA        : 20/10/2025
    ...

Não dá para confiar no acento: na base real o texto vem corrompido na origem
(`RESTRI��O`, `N�O`) e também aparece como `NAO` sem acento. Por isso a
leitura ignora o miolo da palavra e olha só o valor depois dos dois pontos.
Parte dos registros antigos usa outro layout, sem a linha de restrição — nesse
caso o resultado é "indeterminado", nunca um "não" presumido.
"""

import re
import unicodedata
from datetime import date, datetime

RESTRICAO_SIM = "sim"
RESTRICAO_NAO = "nao"
RESTRICAO_INDETERMINADO = "indeterminado"

_RE_RESTRICAO = re.compile(r"RESTRI\S*\s*:\s*(\S+)")
_RE_DATA = re.compile(r"DATA\s*:\s*(\d{2}/\d{2}/\d{4})")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).upper()


def parse_spc(texto: str | None) -> tuple[str, date | None]:
    """Retorna (restricao, data_consulta): restricao é "sim", "nao" ou
    "indeterminado"; data_consulta vem do campo `DATA :` do próprio texto (a
    coluna `scpcconsulta` do SETA vem vazia), ou None se ausente/inválida."""

    if not texto or not texto.strip():
        return RESTRICAO_INDETERMINADO, None

    norm = _normalizar(texto)

    restricao = RESTRICAO_INDETERMINADO
    m = _RE_RESTRICAO.search(norm)
    if m:
        valor = m.group(1)
        if valor == "SIM":
            restricao = RESTRICAO_SIM
        elif valor.startswith("N"):  # NAO / NÃO / N?O com byte corrompido
            restricao = RESTRICAO_NAO

    data_consulta = None
    d = _RE_DATA.search(norm)
    if d:
        try:
            data_consulta = datetime.strptime(d.group(1), "%d/%m/%Y").date()
        except ValueError:
            pass

    return restricao, data_consulta
