"""Base de lojas da TopFama, lida da planilha do Google (uma linha por loja).

A planilha só descreve as lojas (regional, estado, clusters); o filtro de
cobrança continua sendo por `ft.empresa` — aqui os atributos viram uma lista de
códigos de filial, que é o que as consultas usam.
"""

import time
import unicodedata

from sqlalchemy.orm import Session

from . import google_client
from .config import settings

TTL_SEGUNDOS = 600

# campo -> cabeçalhos aceitos (já normalizados: sem acento, maiúsculo)
_CABECALHOS = {
    "filial": ("FILIAL",),
    "nome_com_cod": ("NOME COM COD", "NOME COM CODIGO"),
    "regional": ("REGIONAL",),
    "estado": ("ESTADO", "UF"),
    "cluster_inad": ("CLUSTER INAD", "CLUSTER INADIMPLENCIA"),
    "cluster_populacao": ("CLUSTER POPULACAO", "CLUSTER POP"),
}

_cache: dict = {}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.upper().split())


def _codigo_filial(valor: str) -> str:
    valor = valor.strip()
    # a planilha pode mostrar "6" para a filial "06" (ft.empresa tem 2 caracteres)
    return valor.zfill(2) if valor.isdigit() else valor.upper()


def interpretar(linhas: list[list[str]]) -> list[dict]:
    """Acha a linha de cabeçalho (a primeira que tem FILIAL, entre as 10
    primeiras) e monta um dict por loja. Colunas além de FILIAL são opcionais."""

    for indice, linha in enumerate(linhas[:10]):
        normalizados = [_normalizar(c) for c in linha]
        if "FILIAL" in normalizados:
            cabecalho, corpo = normalizados, linhas[indice + 1 :]
            break
    else:
        raise google_client.GoogleIndisponivel(
            "Não achei a coluna FILIAL na planilha de lojas: confira o cabeçalho da aba"
        )

    posicao = {
        campo: next((cabecalho.index(nome) for nome in nomes if nome in cabecalho), None)
        for campo, nomes in _CABECALHOS.items()
    }

    def celula(linha: list[str], campo: str) -> str | None:
        i = posicao[campo]
        valor = linha[i].strip() if i is not None and i < len(linha) else ""
        return valor or None

    lojas = []
    for linha in corpo:
        filial = celula(linha, "filial")
        if not filial:
            continue
        estado = celula(linha, "estado")
        lojas.append(
            {
                "filial": _codigo_filial(filial),
                "nome_com_cod": celula(linha, "nome_com_cod"),
                "regional": celula(linha, "regional"),
                "estado": estado.upper() if estado else None,
                "cluster_inad": celula(linha, "cluster_inad"),
                "cluster_populacao": celula(linha, "cluster_populacao"),
            }
        )
    return lojas


def listar_lojas(db: Session, *, atualizar: bool = False) -> list[dict]:
    if not atualizar and _cache.get("expira", 0) > time.time():
        return _cache["lojas"]
    linhas = google_client.ler_aba(db, settings.google_sheet_lojas_id, settings.google_sheet_lojas_gid)
    lojas = interpretar(linhas)
    _cache.update(lojas=lojas, expira=time.time() + TTL_SEGUNDOS)
    return lojas


def limpar_cache() -> None:
    _cache.clear()


def _igual(a: str | None, filtros: list[str] | None) -> bool:
    return not filtros or (a is not None and _normalizar(a) in {_normalizar(f) for f in filtros})


def filtrar_lojas(
    lojas: list[dict],
    *,
    regional: list[str] | None = None,
    estado: list[str] | None = None,
    cluster_inad: list[str] | None = None,
    cluster_populacao: list[str] | None = None,
) -> list[dict]:
    return [
        l
        for l in lojas
        if _igual(l["regional"], regional)
        and _igual(l["estado"], estado)
        and _igual(l["cluster_inad"], cluster_inad)
        and _igual(l["cluster_populacao"], cluster_populacao)
    ]


def codigos_por_atributos(
    db: Session,
    *,
    regional: list[str] | None = None,
    estado: list[str] | None = None,
    cluster_inad: list[str] | None = None,
    cluster_populacao: list[str] | None = None,
) -> list[str]:
    """Códigos de filial das lojas que casam com os atributos (pode ser vazio)."""

    filtradas = filtrar_lojas(
        listar_lojas(db),
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
        cluster_populacao=cluster_populacao,
    )
    return [l["filial"] for l in filtradas]


def combinar_lojas(
    db: Session,
    loja: list[str] | None,
    *,
    regional: list[str] | None = None,
    estado: list[str] | None = None,
    cluster_inad: list[str] | None = None,
    cluster_populacao: list[str] | None = None,
) -> list[str] | None:
    """Junta os códigos de loja escolhidos direto com os que vêm dos atributos
    da planilha (interseção). None = sem filtro de loja; lista vazia = nenhuma
    loja casou, e quem consulta deve devolver zero resultados."""

    if not (regional or estado or cluster_inad or cluster_populacao):
        return loja
    dos_atributos = codigos_por_atributos(
        db, regional=regional, estado=estado, cluster_inad=cluster_inad, cluster_populacao=cluster_populacao
    )
    if loja:
        return [c for c in dos_atributos if c in {_codigo_filial(x) for x in loja}]
    return dos_atributos
