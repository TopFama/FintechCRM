import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    # jti identifica esta sessão, para o "Sair" conseguir invalidá-la (tokens_revogados)
    payload = {"sub": subject, "exp": expire, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """Payload de um token de login válido ({"sub", "jti", "exp"}). Token sem
    jti (emitido antes do "Sair" invalidar sessão) não vale mais."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    return payload if payload.get("sub") and payload.get("jti") else None


DISPOSITIVO_DIAS = 90


def create_device_token(user_email: str) -> str:
    """Cookie de "dispositivo conhecido": navegador onde o usuário já entrou
    com a senha certa. Quem tem esse cookie não fica bloqueado pelas senhas
    erradas que outra pessoa tentar na conta (ver rate_limit)."""

    payload = {
        "usr": user_email,
        "typ": "dispositivo",
        "jti": uuid.uuid4().hex,
        "exp": datetime.utcnow() + timedelta(days=DISPOSITIVO_DIAS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_device_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    return payload if payload.get("typ") == "dispositivo" and payload.get("usr") else None


def create_oauth_state(user_email: str, minutes: int = 10) -> str:
    """Parâmetro `state` do OAuth: prova que o retorno do Google pertence a um
    consentimento iniciado por um usuário logado. O e-mail vai em `usr`, não em
    `sub`, para este token nunca ser aceito como token de login."""

    payload = {"usr": user_email, "typ": "oauth_state", "exp": datetime.utcnow() + timedelta(minutes=minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_oauth_state(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    return payload.get("usr") if payload.get("typ") == "oauth_state" else None


_hosts_permitidos = [h.strip().lower() for h in settings.allowed_hosts.split(",") if h.strip()]


def _host_permitido(host: str | None) -> bool:
    host = (host or "").lower().rstrip(".")
    return bool(host) and any(host == h or (h.startswith("*.") and host.endswith(h[1:])) for h in _hosts_permitidos)


def origem_permitida(host: str | None, origin: str | None) -> bool:
    """Chegou por um domínio permitido (Host) e, se veio de navegador (Origin),
    de um site permitido. Vale para HTTP (middleware) e WebSocket."""
    return _host_permitido(host) and (origin is None or _host_permitido(urlparse(origin).hostname))
