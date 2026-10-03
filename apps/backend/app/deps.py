from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_access_token
from .services import pagamentos_seta

bearer_scheme = HTTPBearer(auto_error=False)


def token_da_requisicao(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    # Prioriza o header Authorization (scripts/integrações); o portal (frontend)
    # autentica só pelo cookie httpOnly setado em POST /auth/login.
    return credentials.credentials if credentials else request.cookies.get("access_token")


def usuario_do_token(db: Session, token: str | None) -> models.User:
    """Usuário da sessão do token (HTTP e WebSocket); 401 se não vale."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado")
    if db.get(models.TokenRevogado, payload["jti"]) is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão encerrada; entre de novo")
    user = db.query(models.User).filter(func.lower(models.User.email) == payload["sub"].lower()).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário não encontrado")
    return user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    user = usuario_do_token(db, token_da_requisicao(request, credentials))
    # Atualização automática de tela aberta (?auto=true) não conta como alguém usando
    if request.query_params.get("auto") != "true":
        pagamentos_seta.registrar_atividade()
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só o administrador pode fazer isso")
    return user
