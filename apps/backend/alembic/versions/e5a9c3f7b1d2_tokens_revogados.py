"""tokens revogados: o "Sair" invalida a sessão na hora

Revision ID: e5a9c3f7b1d2
Revises: d4f8b2c6e0a3
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

revision = "e5a9c3f7b1d2"
down_revision = "d4f8b2c6e0a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tokens_revogados",
        sa.Column("jti", sa.String(), nullable=False),
        sa.Column("expira_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(op.f("ix_tokens_revogados_expira_em"), "tokens_revogados", ["expira_em"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tokens_revogados_expira_em"), table_name="tokens_revogados")
    op.drop_table("tokens_revogados")
