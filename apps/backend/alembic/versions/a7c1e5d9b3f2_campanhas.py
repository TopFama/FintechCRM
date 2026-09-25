"""campanhas de cobrança com filtros e templates próprios

Revision ID: a7c1e5d9b3f2
Revises: e8a4b2c6d1f3
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c1e5d9b3f2"
down_revision = "e8a4b2c6d1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campanhas",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("faixa_id", sa.String(), nullable=False),
        sa.Column("ativa", sa.Boolean(), nullable=False),
        sa.Column("modo", sa.String(), server_default="unica", nullable=False),
        sa.Column("data_inicio", sa.Date(), nullable=True),
        sa.Column("data_fim", sa.Date(), nullable=True),
        sa.Column("filtros", sa.JSON(), nullable=False),
        sa.Column("clientes", sa.JSON(), nullable=False),
        sa.Column("clientes_arquivo", sa.String(), nullable=True),
        sa.Column("fonte_valores", sa.String(), server_default="seta", nullable=False),
        sa.Column("planilha_colunas", sa.JSON(), nullable=False),
        sa.Column("planilha_linhas", sa.JSON(), nullable=False),
        sa.Column("recontato_dias", sa.Integer(), nullable=True),
        sa.Column("ultima_execucao", sa.DateTime(), nullable=True),
        sa.Column("ultima_execucao_dia", sa.Date(), nullable=True),
        sa.Column("ultimo_resultado", sa.JSON(), nullable=False),
        sa.Column("arquivada_em", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["faixa_id"], ["faixas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("faixa_id"),
        sa.UniqueConstraint("nome"),
    )


def downgrade() -> None:
    op.drop_table("campanhas")
