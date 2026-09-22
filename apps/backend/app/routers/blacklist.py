from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..utils.document import identify_document

router = APIRouter(prefix="/blacklist", tags=["blacklist"])

MSG_DOCUMENTO_INVALIDO = "Informe o código do cliente (8 dígitos) ou um CPF válido"


def codigos_bloqueados(db: Session) -> tuple[list[str], list[str]]:
    """(códigos SETA, CPFs) bloqueados — a extração do SETA exclui esses
    clientes direto na consulta."""

    rows = db.query(models.ClienteBloqueado.tipo, models.ClienteBloqueado.valor).all()
    return [v for t, v in rows if t == "seta"], [v for t, v in rows if t == "cpf"]


@router.get("", response_model=list[schemas.BlacklistOut])
def list_blacklist(
    busca: str | None = Query(None, description="Trecho do código/CPF"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = db.query(models.ClienteBloqueado)
    if busca:
        digits = "".join(ch for ch in busca if ch.isdigit())
        if digits:
            query = query.filter(models.ClienteBloqueado.valor.contains(digits))
    return query.order_by(models.ClienteBloqueado.created_at.desc()).all()


@router.post("", response_model=schemas.BlacklistOut, status_code=status.HTTP_201_CREATED)
def add_blacklist(
    payload: schemas.BlacklistCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    parsed = identify_document(payload.documento)
    if not parsed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MSG_DOCUMENTO_INVALIDO)
    valor, tipo = parsed
    existing = (
        db.query(models.ClienteBloqueado)
        .filter(models.ClienteBloqueado.tipo == tipo, models.ClienteBloqueado.valor == valor)
        .first()
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esse cliente já está na blacklist")
    item = models.ClienteBloqueado(tipo=tipo, valor=valor, motivo=payload.motivo.strip(), created_by=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/lote", response_model=schemas.BlacklistLoteResult)
def add_blacklist_lote(
    payload: schemas.BlacklistLoteCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Para colar uma lista: o que for válido entra, o resto volta em `invalidos`."""

    ja_existem = {(t, v) for t, v in db.query(models.ClienteBloqueado.tipo, models.ClienteBloqueado.valor)}
    adicionados = repetidos = 0
    invalidos: list[str] = []
    for bruto in payload.documentos:
        if not bruto.strip():
            continue
        parsed = identify_document(bruto)
        if not parsed:
            invalidos.append(bruto.strip())
            continue
        valor, tipo = parsed
        if (tipo, valor) in ja_existem:
            repetidos += 1
            continue
        ja_existem.add((tipo, valor))
        db.add(models.ClienteBloqueado(tipo=tipo, valor=valor, motivo=payload.motivo.strip(), created_by=user.id))
        adicionados += 1
    db.commit()
    return schemas.BlacklistLoteResult(adicionados=adicionados, ja_existiam=repetidos, invalidos=invalidos)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_blacklist(
    item_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    item = db.get(models.ClienteBloqueado, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não está na blacklist")
    db.delete(item)
    db.commit()
