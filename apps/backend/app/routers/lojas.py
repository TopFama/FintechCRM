from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import google_client, lojas, models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/lojas", tags=["lojas"])


def lojas_ou_erro(db: Session, *, atualizar: bool = False) -> list[dict]:
    try:
        return lojas.listar_lojas(db, atualizar=atualizar)
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("", response_model=list[schemas.LojaOut])
def listar(
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None, description="TO, PA, MA ou GO"),
    cluster_inad: list[str] | None = Query(None),
    cluster_populacao: list[str] | None = Query(None),
    atualizar: bool = Query(False, description="Ignora o cache de 10 minutos e relê a planilha"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return lojas.filtrar_lojas(
        lojas_ou_erro(db, atualizar=atualizar),
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
        cluster_populacao=cluster_populacao,
    )


@router.get("/filtros", response_model=schemas.LojaFiltrosOut)
def filtros(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Valores possíveis de cada filtro, para as listas suspensas."""

    todas = lojas_ou_erro(db)

    def distintos(campo: str) -> list[str]:
        return sorted({l[campo] for l in todas if l[campo]})

    return schemas.LojaFiltrosOut(
        regionais=distintos("regional"),
        estados=distintos("estado"),
        clusters_inad=distintos("cluster_inad"),
        clusters_populacao=distintos("cluster_populacao"),
    )
