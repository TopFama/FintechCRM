"""Cifra simétrica para segredos guardados no banco (tokens da Meta e do Google).

Usa MultiFernet com chave primária dedicada (`ENCRYPTION_KEY`) e chave legada
derivada de `JWT_SECRET` para compatibilidade durante a transição.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import settings


def _chave_legada() -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())


def _multi_fernet() -> MultiFernet:
    fernets: list[Fernet] = []
    if settings.encryption_key:
        fernets.append(Fernet(settings.encryption_key.encode()))
    fernets.append(Fernet(_chave_legada()))
    return MultiFernet(fernets)


def cifrar(texto: str) -> str:
    return _multi_fernet().encrypt(texto.encode()).decode()


def decifrar(cifrado: str) -> str | None:
    """None se o valor não abre com nenhuma das chaves."""
    try:
        return _multi_fernet().decrypt(cifrado.encode()).decode()
    except (InvalidToken, Exception):
        return None


def recifrar(cifrado: str) -> str | None:
    """Re-cifra usando a chave principal do MultiFernet (rotate). None se inválido."""
    try:
        return _multi_fernet().rotate(cifrado.encode()).decode()
    except (InvalidToken, Exception):
        return None


def decifrar_chave_nova(cifrado: str) -> str | None:
    """None se o valor não abre diretamente com a ENCRYPTION_KEY primária."""
    if not settings.encryption_key:
        return None
    try:
        return Fernet(settings.encryption_key.encode()).decrypt(cifrado.encode()).decode()
    except (InvalidToken, Exception):
        return None
