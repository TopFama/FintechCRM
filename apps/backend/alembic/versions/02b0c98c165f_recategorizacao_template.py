"""recategorização de template pela Meta (categoria anterior, sugerida e ciente)

Revision ID: 02b0c98c165f
Revises: b8d2f4a6c1e3
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "02b0c98c165f"
down_revision: Union[str, None] = "b8d2f4a6c1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("categoria_anterior", sa.String(), nullable=True))
    op.add_column("templates", sa.Column("categoria_sugerida", sa.String(), nullable=True))
    op.add_column("templates", sa.Column("categoria_ciente", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("templates", "categoria_ciente")
    op.drop_column("templates", "categoria_sugerida")
    op.drop_column("templates", "categoria_anterior")
