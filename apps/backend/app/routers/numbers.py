from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/numbers", tags=["numbers"])


@router.get("", response_model=list[schemas.WhatsappNumberOut])
def list_numbers(
    db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    return db.query(models.WhatsappNumber).order_by(models.WhatsappNumber.created_at.desc()).all()


@router.post("", response_model=schemas.WhatsappNumberOut, status_code=status.HTTP_201_CREATED)
def create_number(
    payload: schemas.WhatsappNumberCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    existing = (
        db.query(models.WhatsappNumber)
        .filter(models.WhatsappNumber.phone_number_id == payload.phone_number_id)
        .first()
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esse phone_number_id já está cadastrado")
    number = models.WhatsappNumber(**payload.model_dump())
    db.add(number)
    db.commit()
    db.refresh(number)
    return number


@router.delete("/{number_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_number(
    number_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    number = db.query(models.WhatsappNumber).get(number_id)
    if not number:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Número não encontrado")
    number.active = False
    db.commit()
