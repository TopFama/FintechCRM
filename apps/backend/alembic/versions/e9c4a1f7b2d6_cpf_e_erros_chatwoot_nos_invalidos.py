"""cpf e erros do Chatwoot nos telefones inválidos

Revision ID: e9c4a1f7b2d6
Revises: d8f2b6e0a4c7
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e9c4a1f7b2d6"
down_revision: str | None = "d8f2b6e0a4c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ERRO_CHATWOOT = """
    lower(coalesce(error_message, '')) LIKE '%131026%'
    OR lower(coalesce(error_message, '')) LIKE '%message undeliverable%'
"""


def upgrade() -> None:
    op.add_column("cobranca_fila", sa.Column("telefones_tentados", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("telefones_invalidos", sa.Column("cpf", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE telefones_invalidos AS t
           SET cpf = coalesce(
               nullif((
                   SELECT q.cpf
                     FROM cobranca_fila AS q
                    WHERE q.codigo_cliente = t.codigo_cliente
                      AND nullif(q.cpf, '') IS NOT NULL
                    ORDER BY q.created_at DESC
                    LIMIT 1
               ), ''),
               nullif((
                   SELECT l.cpf
                     FROM leads AS l
                    WHERE l.codigo_cliente = t.codigo_cliente
                      AND nullif(l.cpf, '') IS NOT NULL
                    ORDER BY l.created_at DESC
                    LIMIT 1
               ), ''),
               ''
           )
        """
    )
    op.alter_column("telefones_invalidos", "cpf", existing_type=sa.String(), nullable=False)

    # Esses retornos já estavam no relatório de erros. O registro separado
    # preserva o telefone recusado antes de o worker trocar pelo próximo campo.
    op.execute(
        f"""
        INSERT INTO telefones_invalidos
            (id, faixa_id, codigo_cliente, cpf, celular_original,
             celular_normalizado, motivo, created_at)
        SELECT
            'chatwoot-131026-' || q.id,
            q.faixa_id,
            q.codigo_cliente,
            coalesce(q.cpf, ''),
            coalesce(nullif(q.celular_original, ''), q.celular),
            q.celular,
            CASE
                WHEN q.error_message LIKE 'Mensagem não pôde ser entregue pelo WhatsApp%'
                    THEN q.error_message
                ELSE 'Mensagem não pôde ser entregue pelo WhatsApp (número sem WhatsApp ou inativo) — Detalhes: '
                     || q.error_message
            END,
            coalesce(q.sent_at, q.created_at)
          FROM cobranca_fila AS q
         WHERE q.status IN ('error', 'sent') AND ({_ERRO_CHATWOOT})
           AND NOT EXISTS (
               SELECT 1
                FROM telefones_invalidos AS t
                WHERE t.faixa_id = q.faixa_id
                  AND t.codigo_cliente = q.codigo_cliente
                  AND t.celular_normalizado = q.celular
           )
        """
    )
    op.execute(
        f"""
        UPDATE cobranca_fila
           SET status = 'error'
         WHERE status IN ('error', 'sent') AND ({_ERRO_CHATWOOT})
        """
    )


def downgrade() -> None:
    op.drop_column("cobranca_fila", "telefones_tentados")
    op.execute("DELETE FROM telefones_invalidos WHERE id LIKE 'chatwoot-131026-%'")
    op.drop_column("telefones_invalidos", "cpf")
