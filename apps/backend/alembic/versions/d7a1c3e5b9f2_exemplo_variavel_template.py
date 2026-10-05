"""exemplo da variável de template para a aprovação na Meta

Revision ID: d7a1c3e5b9f2
Revises: c4e8a2d6f1b3
Create Date: 2026-10-05

Nulo nos templates que já existem: o exemplo só é preciso para enviar um
rascunho criado na plataforma para aprovação.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d7a1c3e5b9f2"
down_revision: str | None = "c4e8a2d6f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("template_variables", sa.Column("exemplo", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("template_variables", "exemplo")
