"""arquivar template (some das listas do CRM sem apagar na Meta)

Revision ID: a7c3e9f1b5d2
Revises: 02b0c98c165f
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9f1b5d2"
down_revision: Union[str, None] = "02b0c98c165f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("arquivado_em", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("templates", "arquivado_em")
