"""botões do template (link fixo, link variável e resposta rápida)

Revision ID: b8d2f4a6c1e3
Revises: a7c3e9b1d5f2
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d2f4a6c1e3"
down_revision: Union[str, None] = "a7c3e9b1d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("botoes", sa.JSON(), server_default="[]", nullable=False))
    op.add_column("template_variables", sa.Column("botao_indice", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("template_variables", "botao_indice")
    op.drop_column("templates", "botoes")
