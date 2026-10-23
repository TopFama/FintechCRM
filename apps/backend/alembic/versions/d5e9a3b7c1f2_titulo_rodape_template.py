"""título e rodapé do template

Revision ID: d5e9a3b7c1f2
Revises: c4d8e2a6b0f1
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e9a3b7c1f2"
down_revision: Union[str, None] = "c4d8e2a6b0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("titulo", sa.String(), nullable=True))
    op.add_column("templates", sa.Column("rodape", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("templates", "rodape")
    op.drop_column("templates", "titulo")
