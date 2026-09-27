"""cópia local das compras no crediário (faixa de compra)

Revision ID: d8f2b6e0a4c7
Revises: c6e0a4b8d2f5
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op

revision = "d8f2b6e0a4c7"
down_revision = "c6e0a4b8d2f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compras_seta",
        sa.Column("codigo_cliente", sa.String(), nullable=False),
        sa.Column("qtd_compras", sa.Integer(), nullable=False),
        sa.Column("ultima_compra", sa.Date(), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("codigo_cliente"),
    )
    op.create_table(
        "sincronizacoes_seta",
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("executado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("nome"),
    )


def downgrade() -> None:
    op.drop_table("sincronizacoes_seta")
    op.drop_table("compras_seta")
