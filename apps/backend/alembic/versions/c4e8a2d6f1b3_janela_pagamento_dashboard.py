"""janela de pagamento do Dashboard em config_parametros

Revision ID: c4e8a2d6f1b3
Revises: a3d5f7b9c1e2
Create Date: 2026-10-04

Nulo = qualquer data após a cobrança. A linha que já existe fica com 7, a
janela que o card usava fixa.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c4e8a2d6f1b3"
down_revision: str | None = "a3d5f7b9c1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("config_parametros", sa.Column("dias_janela_dashboard", sa.Integer(), nullable=True))
    op.execute("UPDATE config_parametros SET dias_janela_dashboard = 7")


def downgrade() -> None:
    op.drop_column("config_parametros", "dias_janela_dashboard")
