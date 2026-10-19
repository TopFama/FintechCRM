"""carência da multa separada da dos juros em config_parametros

Revision ID: d6a1c3e5f7b9
Revises: b8d2f4a6c0e3
Create Date: 2026-10-19

A linha que já existe fica com a caixa "mesma carência" marcada e a carência
da multa igual à dos juros, o que mantém o cálculo de hoje.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d6a1c3e5f7b9"
down_revision: str | None = "b8d2f4a6c0e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("config_parametros", sa.Column("dias_min_multa", sa.Integer(), nullable=True))
    op.add_column(
        "config_parametros",
        sa.Column("mesma_carencia_multa_juros", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute("UPDATE config_parametros SET dias_min_multa = dias_min_juros")
    op.alter_column("config_parametros", "dias_min_multa", nullable=False)


def downgrade() -> None:
    op.drop_column("config_parametros", "mesma_carencia_multa_juros")
    op.drop_column("config_parametros", "dias_min_multa")
