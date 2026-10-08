"""campanha: autorização para usar o valor do SETA quando a planilha não tem valor válido

Revision ID: a7c3e9b1d5f2
Revises: dd623d789df7
Create Date: 2026-10-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9b1d5f2"
down_revision: Union[str, None] = "dd623d789df7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campanhas", sa.Column("valor_seta_autorizado", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("campanhas", "valor_seta_autorizado")
