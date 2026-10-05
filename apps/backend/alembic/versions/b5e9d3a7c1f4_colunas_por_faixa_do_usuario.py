"""ordem das colunas da tabela Por faixa salva por usuário

Revision ID: b5e9d3a7c1f4
Revises: d7a1c3e5b9f2
Create Date: 2026-10-05

Nulo = ordem padrão da tela.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b5e9d3a7c1f4"
down_revision: str | None = "d7a1c3e5b9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("colunas_por_faixa", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "colunas_por_faixa")
