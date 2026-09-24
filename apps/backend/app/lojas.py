"""Base de lojas da TopFama (uma linha por loja): tabela `lojas` do banco,
com carga inicial da planilha Bases_Fintech. A planilha do Google só é lida
se a tabela estiver vazia.

A base só descreve as lojas (regional, estado, clusters); o filtro de
cobrança continua sendo por `ft.empresa` — aqui os atributos viram uma lista de
códigos de filial, que é o que as consultas usam.
"""

import time
import unicodedata

from sqlalchemy.orm import Session

from . import google_client, models
from .config import settings

TTL_SEGUNDOS = 600

# campo -> cabeçalhos aceitos (já normalizados: sem acento, maiúsculo)
_CABECALHOS = {
    "filial": ("FILIAL",),
    "nome_com_cod": ("NOME COM COD", "NOME COM CODIGO"),
    "regional": ("REGIONAL",),
    "estado": ("ESTADO", "UF"),
    "cluster_cobradora": ("CLUSTER COBRADORAS", "CLUSTER COBRADORA", "COBRADORA"),
    "cluster_inad": ("CLUSTER INAD", "CLUSTER INADIMPLENCIA"),
    "cluster_populacao": ("CLUSTER POPULACAO", "CLUSTER POP"),
}

_cache: dict = {}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.upper().split())


def codigo_filial(valor: str) -> str:
    valor = valor.strip()
    # a planilha pode mostrar "6" para a filial "06" (ft.empresa tem 2 caracteres)
    return valor.zfill(2) if valor.isdigit() else valor.upper()


def interpretar(linhas: list[list[str]], *, so_colunas_presentes: bool = False) -> list[dict]:
    """Acha a linha de cabeçalho (a primeira que tem FILIAL, entre as 10
    primeiras) e monta um dict por loja. Colunas além de FILIAL são opcionais;
    com `so_colunas_presentes`, os campos sem coluna na planilha nem entram no
    dict (a sincronização não apaga o que a planilha não tem)."""

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

    presentes = {campo for campo, i in posicao.items() if i is not None}
    lojas = []
    for linha in corpo:
        filial = celula(linha, "filial")
        if not filial:
            continue
        estado = celula(linha, "estado")
        lojas.append(
            {
                "filial": codigo_filial(filial),
                "nome_com_cod": celula(linha, "nome_com_cod"),
                "regional": celula(linha, "regional"),
                "estado": estado.upper() if estado else None,
                "cluster_cobradora": celula(linha, "cluster_cobradora"),
                "cluster_inad": celula(linha, "cluster_inad"),
                "cluster_populacao": celula(linha, "cluster_populacao"),
            }
        )
        if so_colunas_presentes:
            lojas[-1] = {k: v for k, v in lojas[-1].items() if k in presentes}
    return lojas


def listar_lojas(db: Session, *, atualizar: bool = False) -> list[dict]:
    do_banco = db.query(models.Loja).order_by(models.Loja.filial).all()
    if do_banco:
        return [{campo: getattr(l, campo) for campo in _CABECALHOS} for l in do_banco]
    if not atualizar and _cache.get("expira", 0) > time.time():
        return _cache["lojas"]
    linhas = google_client.ler_aba(db, settings.google_sheet_lojas_id, settings.google_sheet_lojas_gid)
    lojas = interpretar(linhas)
    _cache.update(lojas=lojas, expira=time.time() + TTL_SEGUNDOS)
    return lojas


def semear_se_vazio(db: Session) -> None:
    """Carga inicial da tabela `lojas` a partir da planilha Bases_Fintech."""

    from .lojas_iniciais import LOJAS_INICIAIS

    if db.query(models.Loja).first() is not None:
        return
    campos = ("filial", "nome_com_cod", "regional", "estado", "cluster_cobradora", "cluster_inad", "cluster_populacao")
    db.add_all(models.Loja(**dict(zip(campos, linha))) for linha in LOJAS_INICIAIS)
    db.commit()


def sincronizar_com_planilha(db: Session) -> dict:
    """Traz a planilha de lojas do Google para a tabela: a planilha vence nos
    campos que ela tem; lojas que só existem no banco ficam como estão."""

    linhas = google_client.ler_aba(db, settings.google_sheet_lojas_id, settings.google_sheet_lojas_gid)
    da_planilha = interpretar(linhas, so_colunas_presentes=True)
    existentes = {l.filial: l for l in db.query(models.Loja).all()}
    novas = atualizadas = 0
    for dados in da_planilha:
        loja = existentes.get(dados["filial"])
        if loja is None:
            db.add(models.Loja(**dados))
            existentes[dados["filial"]] = dados  # filial repetida na planilha: vale a primeira
            novas += 1
            continue
        if not isinstance(loja, models.Loja):
            continue
        mudou = False
        for campo, valor in dados.items():
            if getattr(loja, campo) != valor:
                setattr(loja, campo, valor)
                mudou = True
        atualizadas += mudou
    db.commit()
    limpar_cache()
    return {"novas": novas, "atualizadas": atualizadas, "sem_mudanca": len(da_planilha) - novas - atualizadas}


def limpar_cache() -> None:
    _cache.clear()


# Opção do filtro de cobradora para as lojas sem cluster de cobradora
SEM_COBRADORA = "Sem cobradora"


def _igual(a: str | None, filtros: list[str] | None, *, vazio: str | None = None) -> bool:
    if not filtros:
        return True
    alvos = {_normalizar(f) for f in filtros}
    if a is None:
        return vazio is not None and _normalizar(vazio) in alvos
    return _normalizar(a) in alvos


def filtrar_lojas(
    lojas: list[dict],
    *,
    regional: list[str] | None = None,
    estado: list[str] | None = None,
    cluster_inad: list[str] | None = None,
    cluster_populacao: list[str] | None = None,
    cobradora: list[str] | None = None,
) -> list[dict]:
    return [
        l
        for l in lojas
        if _igual(l["regional"], regional)
        and _igual(l["estado"], estado)
        and _igual(l["cluster_inad"], cluster_inad)
        and _igual(l["cluster_populacao"], cluster_populacao)
        and _igual(l.get("cluster_cobradora"), cobradora, vazio=SEM_COBRADORA)
    ]


def codigos_por_atributos(
    db: Session,
    *,
    regional: list[str] | None = None,
    estado: list[str] | None = None,
    cluster_inad: list[str] | None = None,
    cluster_populacao: list[str] | None = None,
    cobradora: list[str] | None = None,
) -> list[str]:
    """Códigos de filial das lojas que casam com os atributos (pode ser vazio)."""

    filtradas = filtrar_lojas(
        listar_lojas(db),
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
        cluster_populacao=cluster_populacao,
        cobradora=cobradora,
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
    cobradora: list[str] | None = None,
) -> list[str] | None:
    """Junta os códigos de loja escolhidos direto com os que vêm dos atributos
    da planilha (interseção). None = sem filtro de loja; lista vazia = nenhuma
    loja casou, e quem consulta deve devolver zero resultados."""

    if not (regional or estado or cluster_inad or cluster_populacao or cobradora):
        return loja
    dos_atributos = codigos_por_atributos(
        db,
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
        cluster_populacao=cluster_populacao,
        cobradora=cobradora,
    )
    if loja:
        return [c for c in dos_atributos if c in {codigo_filial(x) for x in loja}]
    return dos_atributos
