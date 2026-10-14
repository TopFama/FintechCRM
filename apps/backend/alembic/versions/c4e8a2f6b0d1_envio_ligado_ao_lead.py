"""envio da fila ligado ao lead que ele cobrou (Efetividade conta cada envio)

Revision ID: c4e8a2f6b0d1
Revises: a7c3e9f1b5d2
Create Date: 2026-10-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a2f6b0d1"
down_revision: Union[str, None] = "a7c3e9f1b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cobranca_fila", sa.Column("lead_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "cobranca_fila_lead_id_fkey", "cobranca_fila", "leads", ["lead_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(op.f("ix_cobranca_fila_lead_id"), "cobranca_fila", ["lead_id"], unique=False)

    # Envios já feitos: o lead mais recente do cliente criado até o envio, pela
    # mesma regra de dispatch_service._lead_do_envio (régua: faixa do envio, sem
    # campanha; campanha/remarketing: o lead daquela campanha).
    op.execute(
        """
        WITH faixa_lead AS (
            SELECT f.id, f.name, COALESCE(
                (SELECT c.id FROM campanhas c WHERE c.faixa_id = f.id LIMIT 1),
                (SELECT 'remarketing:' || r.segmento FROM remarketing_segmentos r
                  WHERE r.faixa_id = f.id AND r.segmento IS NOT NULL LIMIT 1)
            ) AS campanha
            FROM faixas f
        )
        UPDATE cobranca_fila q SET lead_id = (
            SELECT l.id FROM leads l
            WHERE l.codigo_cliente = q.codigo_cliente
              AND l.created_at <= q.sent_at
              AND (
                (fl.campanha IS NOT NULL AND l.campanha_id = fl.campanha)
                OR (fl.campanha IS NULL AND l.faixa = fl.name AND l.campanha_id = '')
              )
            ORDER BY l.created_at DESC
            LIMIT 1)
        FROM faixa_lead fl
        WHERE fl.id = q.faixa_id AND q.status = 'sent' AND q.sent_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cobranca_fila_lead_id"), table_name="cobranca_fila")
    op.drop_constraint("cobranca_fila_lead_id_fkey", "cobranca_fila", type_="foreignkey")
    op.drop_column("cobranca_fila", "lead_id")
