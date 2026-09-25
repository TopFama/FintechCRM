"""tipo da faixa: régua de atraso, campanha ou remarketing

Revision ID: d4f8b2c6e0a3
Revises: c3e7a1b5d9f2
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "d4f8b2c6e0a3"
down_revision = "c3e7a1b5d9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("faixas", sa.Column("tipo", sa.String(), server_default="regua", nullable=False))
    op.create_index(op.f("ix_faixas_tipo"), "faixas", ["tipo"], unique=False)
    # Até aqui a diferença estava só no vínculo (campanhas/remarketing_segmentos).
    op.execute("UPDATE faixas SET tipo = 'campanha' WHERE id IN (SELECT faixa_id FROM campanhas)")
    op.execute("UPDATE faixas SET tipo = 'remarketing' WHERE id IN (SELECT faixa_id FROM remarketing_segmentos)")


def downgrade() -> None:
    op.drop_index(op.f("ix_faixas_tipo"), table_name="faixas")
    op.drop_column("faixas", "tipo")
