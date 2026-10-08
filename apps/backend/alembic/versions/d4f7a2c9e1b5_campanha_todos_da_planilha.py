"""campanha: todos os clientes da planilha e fora da regra de uma cobrança por dia

Revision ID: d4f7a2c9e1b5
Revises: c8e2a4f6b0d1
Create Date: 2026-10-08

- todos_da_planilha: com planilha, entra todo cliente dela com parcela em
  aberto no SETA, em atraso ou não (quem não está em atraso vai para a faixa
  só de campanhas, ex.: "Antecipado").
- incluir_cobrados_hoje: a campanha entra e sai da fila mesmo que o cliente
  já tenha recebido mensagem hoje por outro caminho.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d4f7a2c9e1b5"
down_revision: str | None = "c8e2a4f6b0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campanhas", sa.Column("todos_da_planilha", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "campanhas", sa.Column("incluir_cobrados_hoje", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("campanhas", "incluir_cobrados_hoje")
    op.drop_column("campanhas", "todos_da_planilha")
