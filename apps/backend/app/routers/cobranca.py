from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import cache, cobranca_base, cobranca_relatorio, google_client, lojas as lojas_base, models, schemas, seta_client
from ..cobranca_regras import NOMES_FAIXA_COMPRA
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from ..utils.spc import parse_spc

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


@router.get("/clientes", response_model=schemas.ClientesCobrancaAsyncOut)
def listar_clientes(
    filtros: dict = Depends(filtros_base),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    job = buscar_base_ou_erro(db, filtros)
    if job["status"] != "ready":
        return schemas.ClientesCobrancaAsyncOut(status="processing")

    clientes = job["data"]
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

