from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import cobranca_base, models, schemas, seta_client
from ..cobranca_regras import FAIXAS, FAIXAS_WHATSAPP, NOMES_CLUSTER, NOMES_FAIXA, NOMES_FAIXA_COMPRA
from ..database import get_db
from ..deps import get_current_user
from ..utils.spc import parse_spc

router = APIRouter(prefix="/cobranca", tags=["cobranca"])


@router.get("/regras", response_model=schemas.CobrancaRegrasOut)
def regras(_user: models.User = Depends(get_current_user)):
    """Clusters, faixas de atraso e a matriz WhatsApp — alimenta os filtros da tela."""

    return schemas.CobrancaRegrasOut(
        clusters=NOMES_CLUSTER,
        faixas=NOMES_FAIXA,
        faixas_whatsapp={c: [f for f in NOMES_FAIXA if f in FAIXAS_WHATSAPP[c]] for c in NOMES_CLUSTER},
        primeiro_dia={nome: dmin for nome, dmin, _ in FAIXAS},
        faixas_compra=NOMES_FAIXA_COMPRA,
    )


def buscar_base_ou_erro(db: Session, **filtros) -> list[dict]:
    try:
        return cobranca_base.buscar_base(db, **filtros)
    except cobranca_base.FiltroInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/clientes", response_model=schemas.ClientesCobrancaPage)
def listar_clientes(
    apenas_primeiro_dia: bool = Query(True, description="Só clientes no primeiro dia da faixa (ex.: 21 dias na faixa 21 A 30)"),
    somente_regra_whatsapp: bool = Query(True, description="Aplica a matriz cluster × faixa do WhatsApp"),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    faixa_compra: list[str] | None = Query(None, description="Quantidade de compras no crediário: 1 a 9 ou 10+"),
    loja: list[str] | None = Query(None, description="Código de 2 caracteres da loja do título (ft.empresa)"),
    portador: list[str] | None = Query(None, description="001 TopFama, 114 SYSCO, 216 MJ"),
    status_cliente: list[str] | None = Query(None, description="E, A ou B"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    clientes = buscar_base_ou_erro(
        db,
        apenas_primeiro_dia=apenas_primeiro_dia,
        somente_regra_whatsapp=somente_regra_whatsapp,
        faixas=faixa,
        clusters=cluster,
        faixas_compra=faixa_compra,
        lojas=loja,
        portadores=portador,
        status_cliente=status_cliente,
    )
    pagina = clientes[offset : offset + limit]

    # o texto do SPC é pesado: só se busca para quem aparece na página
    try:
        spc = seta_client.buscar_spc([c["codigo"] for c in pagina])
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    for c in pagina:
        c["spc_restricao"], c["spc_data_consulta"] = parse_spc(spc.get(c["codigo"]))

    return schemas.ClientesCobrancaPage(total=len(clientes), itens=pagina)
