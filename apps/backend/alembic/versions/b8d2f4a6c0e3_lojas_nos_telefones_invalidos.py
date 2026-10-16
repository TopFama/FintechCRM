"""loja do cliente nos telefones inválidos

Revision ID: b8d2f4a6c0e3
Revises: c4e8a2f6b0d1
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b8d2f4a6c0e3"
down_revision: str | None = "c4e8a2f6b0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("telefones_invalidos", sa.Column("lojas", sa.String(), nullable=False, server_default=","))
    # Registros antigos: loja do item da fila do cliente; sem ele, do Lead mais
    # recente com loja (mesma origem que a importação usa).
    op.execute(
        """
        UPDATE telefones_invalidos AS t
           SET lojas = coalesce(
               (
                   SELECT q.lojas
                     FROM cobranca_fila AS q
                    WHERE q.codigo_cliente = t.codigo_cliente
                      AND q.lojas <> ','
                    ORDER BY q.created_at DESC
                    LIMIT 1
               ),
               (
                   SELECT l.lojas
                     FROM leads AS l
                    WHERE l.codigo_cliente = t.codigo_cliente
                      AND l.lojas <> ','
                    ORDER BY l.created_at DESC
                    LIMIT 1
               ),
               ','
           )
        """
    )


def downgrade() -> None:
    op.drop_column("telefones_invalidos", "lojas")
