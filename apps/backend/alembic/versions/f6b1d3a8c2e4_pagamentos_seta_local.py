"""pagamentos do SETA guardados no banco da app (sincronização incremental)

Revision ID: f6b1d3a8c2e4
Revises: e5a9c3f7b1d2
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

revision = "f6b1d3a8c2e4"
down_revision = "e5a9c3f7b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pagamentos_seta",
        sa.Column("titulo_codigo", sa.String(), nullable=False),
        sa.Column("codigo_cliente", sa.String(), nullable=False),
        sa.Column("pagamento", sa.Date(), nullable=False),
        sa.Column("valor", sa.Numeric(14, 2), nullable=False),
        sa.Column("rp", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("titulo_codigo"),
    )
    op.create_index(op.f("ix_pagamentos_seta_codigo_cliente"), "pagamentos_seta", ["codigo_cliente"], unique=False)
    op.create_index(op.f("ix_pagamentos_seta_pagamento"), "pagamentos_seta", ["pagamento"], unique=False)
    op.create_table(
        "pagamentos_seta_clientes",
        sa.Column("codigo_cliente", sa.String(), nullable=False),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("marca_dagua", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("codigo_cliente"),
    )
    op.create_index(
        op.f("ix_pagamentos_seta_clientes_marca_dagua"), "pagamentos_seta_clientes", ["marca_dagua"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pagamentos_seta_clientes_marca_dagua"), table_name="pagamentos_seta_clientes")
    op.drop_table("pagamentos_seta_clientes")
    op.drop_index(op.f("ix_pagamentos_seta_pagamento"), table_name="pagamentos_seta")
    op.drop_index(op.f("ix_pagamentos_seta_codigo_cliente"), table_name="pagamentos_seta")
    op.drop_table("pagamentos_seta")
