"""campanha com envio automático por período, parar campanha e faixa de atraso no item da fila

Revision ID: c3e7a1b5d9f2
Revises: b2d6f0a4c8e1
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "c3e7a1b5d9f2"
down_revision = "b2d6f0a4c8e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cobranca_fila", sa.Column("faixa_atraso", sa.String(), nullable=True))
    op.add_column("campanhas", sa.Column("parada_em", sa.DateTime(), nullable=True))
    # Campanha "só em um dia" vira período de um dia.
    op.execute("UPDATE campanhas SET data_fim = data_inicio WHERE modo = 'unica'")
    op.execute("UPDATE campanhas SET modo = 'recorrente'")
    op.alter_column("campanhas", "modo", server_default="recorrente")
    # Itens de campanha já na fila: faixa de atraso do lead da campanha.
    op.execute(
        """
        UPDATE cobranca_fila q SET faixa_atraso = (
            SELECT l.faixa FROM leads l JOIN campanhas c ON c.id = l.campanha_id
            WHERE c.faixa_id = q.faixa_id AND l.codigo_cliente = q.codigo_cliente
            ORDER BY l.created_at DESC LIMIT 1
        )
        WHERE q.faixa_id IN (SELECT faixa_id FROM campanhas)
        """
    )


def downgrade() -> None:
    op.alter_column("campanhas", "modo", server_default="unica")
    op.drop_column("campanhas", "parada_em")
    op.drop_column("cobranca_fila", "faixa_atraso")
