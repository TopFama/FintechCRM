from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from .. import cobranca_relatorio, models, schemas, seta_client
from ..cobranca_regras import NOMES_FAIXA_COMPRA
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from ..fila_automatica import sem_cobrados_hoje
from ..timezone import hoje_br
from ..utils.spc import parse_spc
from .comum import ClienteSortColumn, buscar_base_ou_erro, filtros_base, ordenar_clientes
from ..utils.xlsx import XLSX_MEDIA_TYPE, build_xlsx, formula_safe

router = APIRouter(prefix="/cobranca", tags=["cobranca"])


@router.get("/regras", response_model=schemas.CobrancaRegrasOut)
def regras(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Clusters, faixas de atraso e a matriz WhatsApp — alimenta os filtros da tela."""

    r = carregar_regras(db)
    return schemas.CobrancaRegrasOut(
        clusters=r.nomes_cluster,
        rotulos_cluster=_rotulos_cluster(r.clusters),
        faixas=r.nomes_faixa,
        faixas_whatsapp={c: r.faixas_whatsapp(c) for c in r.nomes_cluster},
        primeiro_dia={f.nome: f.dia_min for f in r.faixas},
        faixas_compra=NOMES_FAIXA_COMPRA,
    )


def _reais(v) -> str:
    inteiro = v == v.to_integral_value()
    texto = f"{v:,.0f}" if inteiro else f"{v:,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _rotulos_cluster(clusters) -> dict[str, str]:
    """Nome com a faixa de valor pago, pros filtros: "ESPECIAL (R$ 0 a <400)"."""
    rotulos = {}
    for i, c in enumerate(clusters):
        if i + 1 < len(clusters):
            faixa = f"{_reais(c.valor_min)} a <{_reais(clusters[i + 1].valor_min)[3:]}"
        else:
            faixa = f"{_reais(c.valor_min)} ou mais"
        rotulos[c.nome] = f"{c.nome} ({faixa})"
    return rotulos


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
        clientes = ordenar_clientes(clientes, sort_by, sort_dir, db)
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
        clientes = ordenar_clientes(clientes, sort_by, sort_dir, db)

    def celula(c: dict, campo: str):
        v = c.get(campo)
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        if isinstance(v, bool):
            return "Sim" if v else "Não"
        if isinstance(v, str):
            return formula_safe(v)
        return v

    rows = [[celula(c, campo) for _, campo in _COLUNAS_EXPORTACAO] for c in clientes]
    return Response(
        content=build_xlsx([t for t, _ in _COLUNAS_EXPORTACAO], rows),
        media_type=XLSX_MEDIA_TYPE,
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

