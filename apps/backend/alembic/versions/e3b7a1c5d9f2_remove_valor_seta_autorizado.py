"""campanha: valor sempre do SETA, sem autorização de valor da planilha

Revision ID: e3b7a1c5d9f2
Revises: d6a1c3e5f7b9
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "e3b7a1c5d9f2"
down_revision = "d6a1c3e5f7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("campanhas", "valor_seta_autorizado")


def downgrade() -> None:
    op.add_column("campanhas", sa.Column("valor_seta_autorizado", sa.Boolean(), nullable=True))
