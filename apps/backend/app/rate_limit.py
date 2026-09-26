"""Limitador de tentativas em memória — trava força-bruta no login. Simples
de propósito: o backend roda num único processo (ver AGENTS.md), então um
dict em memória basta, sem precisar de Redis ou banco para isso."""

import threading
import time
from collections import defaultdict, deque

LIMITE_TENTATIVAS = 5
JANELA_SEGUNDOS = 15 * 60

_lock = threading.Lock()
_tentativas: dict[str, deque[float]] = defaultdict(deque)


class MuitasTentativas(Exception):
    """Limite de tentativas excedido. Mensagem segura para o usuário."""


def checar(chave: str, limite: int = LIMITE_TENTATIVAS) -> None:
    agora = time.monotonic()
    with _lock:
        fila = _tentativas[chave]
        while fila and agora - fila[0] > JANELA_SEGUNDOS:
            fila.popleft()
        if len(fila) >= limite:
            raise MuitasTentativas("Muitas tentativas de login — tente novamente em alguns minutos")


def registrar_falha(chave: str) -> None:
    with _lock:
        _tentativas[chave].append(time.monotonic())


def limpar(chave: str) -> None:
    with _lock:
        _tentativas.pop(chave, None)
