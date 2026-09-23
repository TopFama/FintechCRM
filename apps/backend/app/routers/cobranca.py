from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from .. import cache, cobranca_base, cobranca_relatorio, google_client, lojas as lojas_base, models, schemas, seta_client
from ..cobranca_regras import NOMES_FAIXA_COMPRA
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from ..fila_automatica import cobrados_hoje
from ..timezone import hoje_br
from ..utils.spc import parse_spc
from .reports import _XLSX_MEDIA_TYPE, _build_xlsx, _formula_safe

router = APIRouter(prefix="/cobranca", tags=["cobranca"])


@router.get("/regras", response_model=schemas.CobrancaRegrasOut)
def regras(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Clusters, faixas de atraso e a matriz WhatsApp — alimenta os filtros da tela."""

    r = carregar_regras(db)
    return schemas.CobrancaRegrasOut(
        clusters=r.nomes_cluster,
        faixas=r.nomes_faixa,
        faixas_whatsapp={c: r.faixas_whatsapp(c) for c in r.nomes_cluster},
        primeiro_dia={f.nome: f.dia_min for f in r.faixas},
        faixas_compra=NOMES_FAIXA_COMPRA,
    )


def filtros_base(
    apenas_primeiro_dia: bool = Query(True, description="Só clientes no primeiro dia da faixa (ex.: 21 dias na faixa 21 A 30)"),
    somente_regra_whatsapp: bool = Query(True, description="Aplica a matriz cluster × faixa do WhatsApp"),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    faixa_compra: list[str] | None = Query(None, description="Quantidade de compras no crediário: 1 a 9 ou 10+"),
    loja: list[str] | None = Query(None, description="Código de 2 caracteres da loja do título (ft.empresa)"),
    regional: list[str] | None = Query(None, description="Regional da loja (planilha de lojas)"),
    estado: list[str] | None = Query(None, description="Estado da loja: TO, PA, MA ou GO"),
    cluster_inad: list[str] | None = Query(None, description="Cluster de inadimplência da loja"),
    cluster_populacao: list[str] | None = Query(None, description="Cluster de população da loja"),
    portador: list[str] | None = Query(None, description="001 TopFama, 114 SYSCO, 216 MJ"),
    status_cliente: list[str] | None = Query(None, description="E, A ou B"),
    restricao_spc: list[str] | None = Query(None, description="sim, nao e/ou indeterminado"),
    vencimento_de: date | None = Query(None, description="Vencimento da parcela mais antiga, a partir de"),
    vencimento_ate: date | None = Query(None, description="Vencimento da parcela mais antiga, até"),
    db: Session = Depends(get_db),
) -> dict:
    """Filtros comuns à listagem e aos relatórios: os dois enxergam os mesmos clientes."""

    try:
        codigos_loja = lojas_base.combinar_lojas(
            db, loja, regional=regional, estado=estado, cluster_inad=cluster_inad, cluster_populacao=cluster_populacao
        )
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return dict(
        apenas_primeiro_dia=apenas_primeiro_dia,
        somente_regra_whatsapp=somente_regra_whatsapp,
        faixas=faixa,
        clusters=cluster,
        faixas_compra=faixa_compra,
        lojas=codigos_loja,
        portadores=portador,
        status_cliente=status_cliente,
        restricoes_spc=restricao_spc,
        vencimento_de=vencimento_de,
        vencimento_ate=vencimento_ate,
    )


def buscar_base_ou_erro(db: Session, filtros: dict) -> dict:
    """{"status": "ready", "data": [...]} ou {"status": "processing", "data":
    None} — ver `cobranca_base.buscar_base`."""

    try:
        return cobranca_base.buscar_base(db, **filtros)
    except cobranca_base.FiltroInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except cache.CacheIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


ClienteSortColumn = Literal[
    "codigo",
    "cpfcnpj",
    "nome",
    "vencimento_mais_antigo",
    "valor_cobrar",
    "qtd_parcelas_cobranca",
    "dias_atraso",
    "faixa",
    "cluster",
]


def _ordenar_clientes(clientes: list[dict], sort_by: str, sort_dir: str, db: Session) -> list[dict]:
    """Ordena uma cópia da lista já carregada em memória (vinda do cache de
    `cobranca_base.buscar_base`) — não refaz a consulta ao SETA. `faixa`
    ordena pela progressão do atraso, mesmo critério da tela."""

    if sort_by == "faixa":
        nomes_faixa = carregar_regras(db).nomes_faixa
        ordem_faixa = {nome: i for i, nome in enumerate(nomes_faixa)}
        valor_fn = lambda c: ordem_faixa.get(c["faixa"], len(ordem_faixa))
    else:
        valor_fn = lambda c: c.get(sort_by)

    ordenados = sorted(clientes, key=lambda c: (valor_fn(c) is None, valor_fn(c) if valor_fn(c) is not None else 0))
    if sort_dir == "desc":
        ordenados.reverse()
    return ordenados


def sem_cobrados_hoje(db: Session, clientes: list[dict]) -> list[dict]:
    """Tira da lista quem já recebeu cobrança hoje (GMT-3, qualquer faixa).
    Cobrado em dia anterior aparece normalmente."""

    bloqueados = cobrados_hoje(db)
    return [c for c in clientes if c["codigo"] not in bloqueados]


@router.get("/clientes", response_model=schemas.ClientesCobrancaAsyncOut)
def listar_clientes(
    filtros: dict = Depends(filtros_base),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: ClienteSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    job = buscar_base_ou_erro(db, filtros)
    if job["status"] != "ready":
        return schemas.ClientesCobrancaAsyncOut(status="processing")

    clientes = sem_cobrados_hoje(db, job["data"])
    if sort_by:
        clientes = _ordenar_clientes(clientes, sort_by, sort_dir, db)
    pagina = clientes[offset : offset + limit]

    # o texto do SPC é pesado: só se busca (para a data da consulta) de quem aparece na página
    try:
        spc = seta_client.buscar_spc([c["codigo"] for c in pagina])
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    for c in pagina:
        _, c["spc_data_consulta"] = parse_spc(spc.get(c["codigo"]))

    return schemas.ClientesCobrancaAsyncOut(
        status="ready", data=schemas.ClientesCobrancaPage(total=len(clientes), itens=pagina)
    )


_COLUNAS_EXPORTACAO = [
    ("Código", "codigo"), ("Nome", "nome"), ("CPF/CNPJ", "cpfcnpj"), ("Celular", "celular"),
    ("Cluster", "cluster"), ("Faixa", "faixa"), ("Dias de atraso", "dias_atraso"),
    ("Parcelas na cobrança", "qtd_parcelas_cobranca"), ("Valor em aberto", "valor_em_aberto"),
    ("Valor a cobrar", "valor_cobrar"), ("Vencimento mais antigo", "vencimento_mais_antigo"),
    ("Status", "status_descricao"), ("Loja do cadastro", "loja_cadastro"), ("Lojas", "lojas"),
    ("Qtd. compras", "qtd_compras"), ("Restrição SPC", "spc_restricao"), ("Entra no WhatsApp", "entra_whatsapp"),
]


@router.get("/clientes/exportar.xlsx")
def exportar_clientes(
    filtros: dict = Depends(filtros_base),
    sort_by: ClienteSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Todos os clientes filtrados (não só a página), na mesma ordem da tela."""

    job = buscar_base_ou_erro(db, filtros)
    if job["status"] != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A base de cobrança ainda está sendo calculada. Tente exportar de novo em instantes."
        )
    clientes = sem_cobrados_hoje(db, job["data"])
    if sort_by:
        clientes = _ordenar_clientes(clientes, sort_by, sort_dir, db)

    def celula(c: dict, campo: str):
        v = c.get(campo)
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        if isinstance(v, bool):
            return "Sim" if v else "Não"
        if isinstance(v, str):
            return _formula_safe(v)
        return v

    rows = [[celula(c, campo) for _, campo in _COLUNAS_EXPORTACAO] for c in clientes]
    return Response(
        content=_build_xlsx([t for t, _ in _COLUNAS_EXPORTACAO], rows),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="clientes_cobranca_{hoje_br():%Y%m%d}.xlsx"'},
    )


@router.get("/relatorio", response_model=schemas.RelatorioCobrancaAsyncOut)
def relatorio(
    filtros: dict = Depends(filtros_base),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Quantidade e valor em aberto de clientes por cluster (linhas) × faixa de
    atraso (colunas), no total e só entre os com restrição no SPC."""

    job = buscar_base_ou_erro(db, filtros)
    if job["status"] != "ready":
        return schemas.RelatorioCobrancaAsyncOut(status="processing")

    clientes = job["data"]
    r = carregar_regras(db)
    return schemas.RelatorioCobrancaAsyncOut(
        status="ready",
        data=schemas.RelatorioCobrancaOut(
            clusters=r.nomes_cluster,
            faixas=r.nomes_faixa,
            quantidade=cobranca_relatorio.montar_matriz(clientes, r),
            quantidade_com_restricao_spc=cobranca_relatorio.montar_matriz(clientes, r, apenas_com_restricao_spc=True),
            valor_em_aberto=cobranca_relatorio.montar_matriz_valor(clientes, r),
        ),
    )

