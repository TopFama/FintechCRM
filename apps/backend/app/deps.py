from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    # Prioriza o header Authorization (scripts/integrações); o portal (frontend)
    # autentica só pelo cookie httpOnly setado em POST /auth/login.
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    email = decode_access_token(token)
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado")
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário não encontrado")
    return user
