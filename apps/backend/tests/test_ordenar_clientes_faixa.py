"""Ordenação da coluna Faixa (prévia da campanha e Cobrança):
1. Faixas na ordem do atraso; dentro da faixa, pelos dias (em Antecipado, o
   vencimento mais distante primeiro).
2. Decrescente inverte as duas coisas; cliente sem faixa fica no fim nas duas direções.
3. Faixa fora das regras fica onde os dias dela cairiam.

Sem banco: as regras são substituídas.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "segredo-de-teste-ordenar-faixa-123456")
os.environ.setdefault("ADMIN_PASSWORD", "senha-admin-teste-ordenar-faixa")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_ordenar_faixa")

from app.cobranca_regras import REGRAS_PADRAO, FaixaAtraso, Regras
from app.routers.comum import ordenar_clientes

REGRAS = Regras(
    clusters=REGRAS_PADRAO.clusters,
    faixas=(
        FaixaAtraso("Antecipado", -365, -2, so_campanhas=True),
        FaixaAtraso("-1", -1, -1),
        FaixaAtraso("1", 1, 1),
        FaixaAtraso("2", 2, 2),
        FaixaAtraso("3 A 10", 3, 10),
        FaixaAtraso("21 A 30", 21, 30),
    ),
    whatsapp=frozenset(),
    juros=REGRAS_PADRAO.juros,
)

# Na ordem da base: do mais atrasado para o menos
CLIENTES = [
    {"codigo": "a", "faixa": "21 A 30", "dias_atraso": 25},
    {"codigo": "b", "faixa": "15", "dias_atraso": 15},  # dia sem faixa nas regras
    {"codigo": "c", "faixa": "3 A 10", "dias_atraso": 9},
    {"codigo": "d", "faixa": "3 A 10", "dias_atraso": 4},
    {"codigo": "e", "faixa": "1", "dias_atraso": 1},
    {"codigo": "f", "faixa": None, "dias_atraso": 0},
    {"codigo": "g", "faixa": "Antecipado", "dias_atraso": -1},
    {"codigo": "h", "faixa": "Antecipado", "dias_atraso": -5},
    {"codigo": "i", "faixa": "Antecipado", "dias_atraso": -300},
]


def _ordem(direcao: str) -> list[str]:
    with patch("app.routers.comum.carregar_regras", return_value=REGRAS):
        return [c["codigo"] for c in ordenar_clientes(CLIENTES, "faixa", direcao, MagicMock())]


print("1. Crescente")
assert _ordem("asc") == ["i", "h", "g", "e", "d", "c", "b", "a", "f"], _ordem("asc")
print("  OK")

print("2. Decrescente")
assert _ordem("desc") == ["a", "b", "c", "d", "e", "g", "h", "i", "f"], _ordem("desc")
print("  OK")

print("OK")
