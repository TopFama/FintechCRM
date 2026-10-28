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
    # Histórico: o template do par faixa+número que enviou (único por faixa e número)
    op.execute(
        """
        UPDATE cobranca_fila SET template_id = (
            SELECT fe.template_id FROM faixa_envios fe
            WHERE fe.faixa_id = cobranca_fila.faixa_id AND fe.whatsapp_number_id = cobranca_fila.whatsapp_number_id
        )
        WHERE whatsapp_number_id IS NOT NULL AND sent_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_cobranca_fila_template_id", "cobranca_fila", type_="foreignkey")
    op.drop_index(op.f("ix_cobranca_fila_template_id"), table_name="cobranca_fila")
    op.drop_column("cobranca_fila", "template_id")
