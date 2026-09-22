import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from .. import models, rate_limit, schemas
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("auth")

COOKIE_NAME = "access_token"


@router.post("/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
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
    # O portal (frontend) não guarda mais o token em localStorage — fica só neste
    # cookie httpOnly, inacessível a JavaScript (mitiga roubo de sessão via XSS).
    # O access_token continua na resposta só para uso programático da API
    # (scripts de validação, integrações) via header Authorization: Bearer.
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return schemas.LoginResponse(access_token=token, is_admin=user.is_admin)


@router.post("/logout")
def logout(response: Response, _user: models.User = Depends(get_current_user)):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
