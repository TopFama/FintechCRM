"""Filtros por coluna (estilo Excel) dos relatórios, num só mecanismo para os cinco.

O parâmetro `filtros` é um JSON {coluna: {"valores": [...], "de": ..., "ate": ...}}.
`valores` restringe aos valores marcados ("" = vazio); `de`/`ate` é o
intervalo (datas ISO nas colunas de data, números nas de valor); os dois
juntos valem em conjunto. Relatórios em SQL usam `aplicar`/`valores_distintos`;
o "Quem pagou", que é uma lista em memória (cache do SETA), usa
`filtrar_memoria`/`valores_memoria` com o mesmo contrato."""

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, Query
from sqlalchemy import String, and_, cast, false, or_, true

from .timezone import inicio_do_dia_utc

LIMITE_VALORES = 500


@dataclass(frozen=True)
class Coluna:
    """`expr` é a expressão SQL da coluna (ou, em memória, a função linha → valor).
    tipo: texto | multi (lista de itens, ex.: lojas ",07,09,") | data | numero.
    `tambem`: segunda expressão que também casa com os valores marcados (texto)."""

    expr: Any
    tipo: str = "texto"
    tambem: Any = None


def filtros_da_query(
    filtros: str | None = Query(None, description='JSON {"coluna": {"valores": [...], "de": "...", "ate": "..."}}'),
) -> dict[str, dict]:
    """Dependência dos endpoints: lê o JSON e valida a forma (as colunas, cada relatório valida)."""

    if not filtros:
        return {}
    try:
        dados = json.loads(filtros)
        for f in dados.values():
            valores = f.get("valores")
            if valores is not None and not (isinstance(valores, list) and all(isinstance(v, str) for v in valores)):
                raise ValueError
        return dados
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Filtros de coluna inválidos")


def _decimal(valor) -> Decimal:
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        raise HTTPException(422, "Valor inválido no filtro de coluna")


def _data(valor) -> date:
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise HTTPException(422, "Data inválida no filtro de coluna")


def _valores_sql(c: Coluna, valores: list[str]):
    vazio = "" in valores
    marcados = [v for v in valores if v]
    if c.tipo == "multi":
        partes = [c.expr.like(f"%,{v},%") for v in marcados]
        vazio_sql = or_(c.expr.is_(None), c.expr.in_(["", ","]))
    elif c.tipo == "numero":
        partes = [c.expr.in_([_decimal(v) for v in marcados])] if marcados else []
        vazio_sql = c.expr.is_(None)
    else:
        partes = [e.in_(marcados) for e in (c.expr, c.tambem) if e is not None] if marcados else []
        vazio_sql = or_(c.expr.is_(None), c.expr == "")
    if vazio:
        partes.append(vazio_sql)
    return or_(*partes) if partes else false()


def _intervalo_sql(c: Coluna, de, ate):
    conds = [true()]
    if c.tipo == "data":
        # mesma regra de período dos relatórios (dias de Brasília sobre UTC)
        if de:
            conds.append(c.expr >= inicio_do_dia_utc(_data(de)))
        if ate:
            conds.append(c.expr < inicio_do_dia_utc(_data(ate) + timedelta(days=1)))
    else:
        if de not in (None, ""):
            conds.append(c.expr >= _decimal(de))
        if ate not in (None, ""):
            conds.append(c.expr <= _decimal(ate))
    return and_(*conds)


def _condicao(c: Coluna, f: dict):
    conds = [true()]
    if f.get("valores") is not None:
        conds.append(_valores_sql(c, f["valores"]))
    if f.get("de") or f.get("ate"):
        conds.append(_intervalo_sql(c, f.get("de"), f.get("ate")))
    return and_(*conds)


def _coluna(mapa: dict[str, Coluna], nome: str) -> Coluna:
    if nome not in mapa:
        raise HTTPException(422, f"Coluna sem filtro: {nome}")
    return mapa[nome]


def aplicar(query, mapa: dict[str, Coluna], filtros: dict | None, ignorar: str | None = None):
    """Filtra a query pelas colunas de `filtros` (menos `ignorar`)."""

    for nome, f in (filtros or {}).items():
        c = _coluna(mapa, nome)
        if nome != ignorar:
            query = query.filter(_condicao(c, f))
    return query


def valores_distintos(query, mapa: dict[str, Coluna], filtros: dict | None, coluna: str, busca: str | None):
    """Valores da coluna dentro dos demais filtros ativos, como na lista do
    Excel: (valores, truncado). Vazio vem como ""."""

    c = _coluna(mapa, coluna)
    if c.tipo == "data":
        raise HTTPException(422, "Coluna de data filtra por intervalo")
    q = aplicar(query, mapa, filtros, ignorar=coluna).order_by(None)
    v = c.expr.label("v")
    q = q.with_entities(v).distinct()
    if busca and c.tipo != "multi":
        q = q.filter(cast(c.expr, String).ilike(f"%{busca.replace(',', '.') if c.tipo == 'numero' else busca}%"))
    if c.tipo == "multi":
        # poucas combinações distintas (ex.: ",07,09,"): separa em Python
        brutos = [r.v or "" for r in q.all()]
        itens = {i for b in brutos for i in b.split(",") if i}
        if any(not b.strip(",") for b in brutos):
            itens.add("")
        itens = sorted(itens, key=lambda i: (i != "", i))
        if busca:
            itens = [i for i in itens if busca.lower() in i.lower()]
        return itens[:LIMITE_VALORES], len(itens) > LIMITE_VALORES
    linhas = [str(r.v) if r.v is not None else "" for r in q.order_by(v).limit(LIMITE_VALORES + 1).all()]
    valores = list(dict.fromkeys(linhas))
    if "" in valores:  # o vazio vem primeiro (no Postgres o NULL ordena por último)
        valores.insert(0, valores.pop(valores.index("")))
    return valores[:LIMITE_VALORES], len(valores) > LIMITE_VALORES


# --- Relatório em memória (Quem pagou) ----------------------------------------


def _celulas(c: Coluna, linha: dict) -> list:
    v = c.expr(linha)
    if c.tipo == "multi":
        return list(v) or [""]
    return [v if v not in (None, "") else ""]


def _chave(c: Coluna, valor):
    return (_decimal(valor) if valor != "" else "") if c.tipo == "numero" else valor


def _passa(c: Coluna, f: dict, linha: dict) -> bool:
    celulas = [_chave(c, x) for x in _celulas(c, linha)]
    if f.get("valores") is not None:
        marcados = {_chave(c, v) for v in f["valores"]}
        if not any(x in marcados for x in celulas):
            return False
    if f.get("de") not in (None, "") and not any(x != "" and x >= _decimal(f["de"]) for x in celulas):
        return False
    if f.get("ate") not in (None, "") and not any(x != "" and x <= _decimal(f["ate"]) for x in celulas):
        return False
    return True


def filtrar_memoria(linhas: list[dict], mapa: dict[str, Coluna], filtros: dict | None, ignorar: str | None = None):
    ativos = [(_coluna(mapa, n), f) for n, f in (filtros or {}).items() if n != ignorar]
    return [l for l in linhas if all(_passa(c, f, l) for c, f in ativos)]


def valores_memoria(linhas: list[dict], mapa: dict[str, Coluna], filtros: dict | None, coluna: str, busca: str | None):
    c = _coluna(mapa, coluna)
    visiveis = filtrar_memoria(linhas, mapa, filtros, ignorar=coluna)
    itens = {str(x) for l in visiveis for x in _celulas(c, l)}
    if busca:
        itens = {i for i in itens if busca.replace(",", ".").lower() in i.lower()}
    ordenados = sorted(itens, key=lambda i: (i != "", _decimal(i) if c.tipo == "numero" and i else i))
    return ordenados[:LIMITE_VALORES], len(ordenados) > LIMITE_VALORES
