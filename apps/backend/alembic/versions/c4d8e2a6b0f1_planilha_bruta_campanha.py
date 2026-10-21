"""campanha guarda a planilha como subiu e o mapeamento de colunas

Revision ID: c4d8e2a6b0f1
Revises: e3b7a1c5d9f2
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d8e2a6b0f1"
down_revision = "e3b7a1c5d9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campanhas", sa.Column("planilha_bruta", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("campanhas", sa.Column("planilha_mapeamento", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("campanhas", "planilha_mapeamento")
    op.drop_column("campanhas", "planilha_bruta")
