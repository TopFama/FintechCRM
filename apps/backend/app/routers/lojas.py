from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
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
    cobradora: list[str] | None = Query(None, description='Cluster de cobradora da loja, ou "Sem cobradora"'),
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
        cobradora=cobradora,
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
        cobradoras=distintos("cluster_cobradora")
        + ([lojas.SEM_COBRADORA] if any(not l.get("cluster_cobradora") for l in todas) else []),
    )


# --- Edição (tela Configurações → Lojas) ---


def _loja_ou_404(db: Session, filial: str) -> models.Loja:
    loja = db.get(models.Loja, lojas.codigo_filial(filial))
    if loja is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loja não encontrada")
    return loja


def _como_dict(loja: models.Loja) -> dict:
    return {campo: getattr(loja, campo) for campo in schemas.LojaOut.model_fields}


@router.post("", response_model=schemas.LojaOut, status_code=status.HTTP_201_CREATED)
def criar(dados: schemas.LojaNovaIn, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    filial = lojas.codigo_filial(dados.filial or "")
    if not filial:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe o código da filial")
    if len(filial) > 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código da filial tem no máximo 4 caracteres")
    if db.get(models.Loja, filial) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A filial {filial} já está cadastrada")
    loja = models.Loja(filial=filial, **dados.model_dump(exclude={"filial"}))
    db.add(loja)
    db.commit()
    lojas.limpar_cache()
    return _como_dict(loja)


@router.put("/{filial}", response_model=schemas.LojaOut)
def editar(
    filial: str,
    dados: schemas.LojaIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    loja = _loja_ou_404(db, filial)
    for campo, valor in dados.model_dump().items():
        setattr(loja, campo, valor)
    db.commit()
    lojas.limpar_cache()
    return _como_dict(loja)


@router.delete("/{filial}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(filial: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    db.delete(_loja_ou_404(db, filial))
    db.commit()
    lojas.limpar_cache()


@router.post("/sincronizar", response_model=schemas.SincronizacaoLojasOut)
def sincronizar(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Atualiza a tabela com a planilha de lojas do Google (a planilha vence
    nos campos que tem; lojas só do banco ficam)."""

    try:
        return lojas.sincronizar_com_planilha(db)
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/colunas-planilha")
async def colunas_planilha(file: UploadFile = File(...), _user: models.User = Depends(get_current_user)):
    """Colunas do relatório .xlsx (com exemplos), para escolher a de loja."""

    from ..campanhas import colunas_planilha as ler_colunas
    from .uploads import _ler_planilha_limitada

    content = await _ler_planilha_limitada(file)
    try:
        return ler_colunas(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/ler-planilha")
async def ler_planilha(
    file: UploadFile = File(...),
    coluna: int | None = Query(None, ge=0, description="Índice da coluna de loja escolhida na tela"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Relatório .xlsx de lojas → códigos de filial, para marcar as lojas de
    um filtro de uma vez, pela coluna escolhida (sem ela, a coluna FILIAL,
    LOJA, CÓDIGO…)."""

    from ..campanhas import ler_lojas
    from .uploads import _ler_planilha_limitada

    content = await _ler_planilha_limitada(file)
    try:
        return ler_lojas(db, file.filename or "", content, coluna)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
