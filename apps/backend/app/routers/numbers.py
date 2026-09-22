from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/numbers", tags=["numbers"])


@router.get("", response_model=list[schemas.WhatsappNumberOut])
def list_numbers(
    db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    return (
        db.query(models.WhatsappNumber)
        .options(selectinload(models.WhatsappNumber.meta_token))
        # números importados juntos têm o mesmo created_at: desempata para a ordem não mudar a cada edição
        .order_by(models.WhatsappNumber.created_at.desc(), models.WhatsappNumber.display_phone_number)
        .all()
    )


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

    if payload.meta_token_id:
        token = db.get(models.MetaToken, payload.meta_token_id)
        if not token or not token.ativo:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Token da Meta não encontrado ou inativo"
            )

    if payload.chatwoot_inbox_id is not None and payload.chatwoot_inbox_id <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ID da inbox do Chatwoot deve ser um inteiro positivo",
        )

    number = models.WhatsappNumber(**payload.model_dump())
    db.add(number)
    db.commit()
    db.refresh(number)
    return number


@router.patch("/{number_id}", response_model=schemas.WhatsappNumberOut)
def update_number(
    number_id: str,
    payload: schemas.WhatsappNumberUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    number = db.get(models.WhatsappNumber, number_id)
    if not number:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Número não encontrado")

    if "label" in payload.model_fields_set:
        number.label = payload.label or ""

    if "active" in payload.model_fields_set and payload.active is not None:
        number.active = payload.active

    if "meta_token_id" in payload.model_fields_set:
        if payload.meta_token_id is not None:
            token = db.get(models.MetaToken, payload.meta_token_id)
            if not token or not token.ativo:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Token da Meta não encontrado ou inativo"
                )
            number.meta_token_id = payload.meta_token_id
        else:
            number.meta_token_id = None

    if "chatwoot_inbox_id" in payload.model_fields_set:
        if payload.chatwoot_inbox_id is not None:
            if payload.chatwoot_inbox_id <= 0:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "ID da inbox do Chatwoot deve ser um inteiro positivo",
                )
            number.chatwoot_inbox_id = payload.chatwoot_inbox_id
        else:
            number.chatwoot_inbox_id = None

    db.commit()
    db.refresh(number)
    return number


@router.delete("/{number_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_number(
    number_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    number = db.get(models.WhatsappNumber, number_id)
    if not number:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Número não encontrado")
    number.active = False
    db.commit()
