import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import models, rate_limit, schemas
from ..database import get_db
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("auth")


@router.post("/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "desconhecido"
    chave = f"{payload.email.lower()}:{ip}"
    try:
        rate_limit.checar(chave)
    except rate_limit.MuitasTentativas as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc

    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        rate_limit.registrar_falha(chave)
        logger.warning("Login falhou para %s (ip %s)", payload.email, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email ou senha inválidos")

    rate_limit.limpar(chave)
    token = create_access_token(subject=user.email)
    return schemas.LoginResponse(access_token=token)
