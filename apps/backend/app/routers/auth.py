import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, rate_limit, schemas
from ..config import settings
from ..database import get_db
from ..deps import bearer_scheme, get_current_user, token_da_requisicao
from ..security import (
    DISPOSITIVO_DIAS,
    create_access_token,
    create_device_token,
    decode_access_token,
    decode_device_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("auth")

COOKIE_NAME = "access_token"
COOKIE_DISPOSITIVO = "dispositivo"
# Senhas erradas vindas de navegador desconhecido: trava só navegadores
# desconhecidos daquela conta. Quem já entrou neste navegador (cookie de
# dispositivo) tem um contador próprio e não é bloqueado por um ataque de fora.
LIMITE_CONTA = 10
LIMITE_DISPOSITIVO = 5


def _chave_tentativas(email: str, request: Request) -> tuple[str, int]:
    dispositivo = decode_device_token(request.cookies.get(COOKIE_DISPOSITIVO))
    if dispositivo and dispositivo["usr"].lower() == email:
        return f"dispositivo:{email}:{dispositivo['jti']}", LIMITE_DISPOSITIVO
    return f"conta:{email}", LIMITE_CONTA


@router.post("/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "desconhecido"
    email = payload.email.strip().lower()
    chave, limite = _chave_tentativas(email, request)
    try:
        rate_limit.checar(chave, limite)
    except rate_limit.MuitasTentativas as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc

    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
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
    response.set_cookie(
        COOKIE_DISPOSITIVO,
        create_device_token(user.email.lower()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=DISPOSITIVO_DIAS * 24 * 60 * 60,
        path="/auth",
    )
    return schemas.LoginResponse(access_token=token, is_admin=user.is_admin)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    # O token assinado valeria até expirar; guardado aqui, deixa de valer já.
    token = decode_access_token(token_da_requisicao(request, credentials) or "")
    if token:
        agora = datetime.utcnow()
        db.query(models.TokenRevogado).filter(models.TokenRevogado.expira_em < agora).delete(synchronize_session=False)
        db.merge(models.TokenRevogado(jti=token["jti"], expira_em=datetime.utcfromtimestamp(token["exp"])))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
