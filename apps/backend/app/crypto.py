"""Cifra simétrica para segredos guardados no banco (refresh token do Google).

A chave é derivada do `JWT_SECRET`: quem tem o banco mas não tem o `.env` não
lê o segredo. Trocar o `JWT_SECRET` invalida o que foi cifrado — o efeito é só
pedir a conexão de novo.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    chave = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(chave)


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def decifrar(cifrado: str) -> str | None:
    """None se o valor não abre com a chave atual (ex.: `JWT_SECRET` trocado)."""

    try:
        return _fernet().decrypt(cifrado.encode()).decode()
    except InvalidToken:
        return None
