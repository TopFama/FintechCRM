"""template usado no envio do item da fila (painel de mensagens por template)

Revision ID: a7c3e5f1b9d2
Revises: d5e9a3b7c1f2
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3e5f1b9d2"
down_revision = "d5e9a3b7c1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cobranca_fila", sa.Column("template_id", sa.String(), nullable=True))
    op.create_index(op.f("ix_cobranca_fila_template_id"), "cobranca_fila", ["template_id"], unique=False)
    op.create_foreign_key(
        "fk_cobranca_fila_template_id", "cobranca_fila", "templates", ["template_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_cobranca_fila_template_id", "cobranca_fila", type_="foreignkey")
    op.drop_index(op.f("ix_cobranca_fila_template_id"), table_name="cobranca_fila")
    op.drop_column("cobranca_fila", "template_id")
