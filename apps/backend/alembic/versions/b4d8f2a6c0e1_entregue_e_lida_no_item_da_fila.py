"""entregue e lida do item da fila (webhook do Chatwoot)

Revision ID: b4d8f2a6c0e1
Revises: a7c3e5f1b9d2
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "b4d8f2a6c0e1"
down_revision = "a7c3e5f1b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cobranca_fila", sa.Column("entregue_em", sa.DateTime(), nullable=True))
    op.add_column("cobranca_fila", sa.Column("lida_em", sa.DateTime(), nullable=True))
    # O webhook acha o item pelo id da mensagem a cada aviso de status
    op.create_index(op.f("ix_cobranca_fila_whatsapp_message_id"), "cobranca_fila", ["whatsapp_message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cobranca_fila_whatsapp_message_id"), table_name="cobranca_fila")
    op.drop_column("cobranca_fila", "lida_em")
    op.drop_column("cobranca_fila", "entregue_em")
