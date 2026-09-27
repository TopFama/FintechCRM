"""índices das leituras por período e da sincronização de pagamentos

Dashboard, Quem pagou e Efetividade filtram leads pela data da cobrança e a
fila pela data de envio/entrada; a sincronização de pagamentos agrega a
primeira e a última cobrança de cada cliente. Sem índice, todas liam a tabela
inteira.

Revision ID: b4d8f2a6c0e3
Revises: a3c7e1f5b9d2
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

revision = "b4d8f2a6c0e3"
down_revision = "a3c7e1f5b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f("ix_leads_cobrado_em"), "leads", ["cobrado_em"], unique=False)
    op.create_index(
        "ix_leads_cobrados_cliente",
        "leads",
        ["codigo_cliente", "cobrado_em"],
        unique=False,
        postgresql_where=sa.text("status = 'cobrado'"),
    )
    op.create_index(op.f("ix_cobranca_fila_sent_at"), "cobranca_fila", ["sent_at"], unique=False)
    op.create_index(op.f("ix_cobranca_fila_created_at"), "cobranca_fila", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cobranca_fila_created_at"), table_name="cobranca_fila")
    op.drop_index(op.f("ix_cobranca_fila_sent_at"), table_name="cobranca_fila")
    op.drop_index("ix_leads_cobrados_cliente", table_name="leads")
    op.drop_index(op.f("ix_leads_cobrado_em"), table_name="leads")
