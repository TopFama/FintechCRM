from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import require_admin
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    return db.query(models.User).order_by(models.User.created_at).all()


@router.post("", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    # E-mail sem diferença de maiúsculas, igual ao login: "Bruno@" e "bruno@" são a mesma conta
    email = payload.email.strip().lower()
    existing = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um usuário com esse email")
    # Usuário criado por aqui nunca nasce admin: tem acesso a tudo que o admin tem,
    # menos gerenciar outros usuários (só quem já é admin passa por require_admin).
    user = models.User(email=email, password_hash=hash_password(payload.password), is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode excluir seu próprio usuário")
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    # Planilhas, leads, blacklist, campanhas e a conexão do Google guardam quem
    # criou (FK sem ON DELETE): passam para o admin que está excluindo, senão o
    # Postgres recusa a exclusão. Não zera: Lead.created_by vazio significa
    # "extração automática" e seria expirado no fim da janela.
    for coluna in (
        models.UploadLog.uploaded_by,
        models.Lead.created_by,
        models.ClienteBloqueado.created_by,
        models.Campanha.created_by,
        models.IntegracaoGoogle.connected_by,
    ):
        db.query(coluna.class_).filter(coluna == user.id).update({coluna: admin.id}, synchronize_session=False)
    db.delete(user)
    db.commit()
