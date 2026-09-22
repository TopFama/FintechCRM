"""cascata ao excluir token ou numero

Revision ID: 2bb816634f94
Revises: 35d34cddd7bb
Create Date: 2026-09-22 12:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2bb816634f94'
down_revision: Union[str, None] = '35d34cddd7bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Excluir um token da Meta agora leva junto os números que dependiam dele
    # (antes só desvinculava, com SET NULL, e a exclusão do token era bloqueada
    # se houvesse número vinculado).
    op.drop_constraint(
        'fk_whatsapp_numbers_meta_token_id_meta_tokens', 'whatsapp_numbers', type_='foreignkey'
    )
    op.create_foreign_key(
        'fk_whatsapp_numbers_meta_token_id_meta_tokens',
        'whatsapp_numbers', 'meta_tokens', ['meta_token_id'], ['id'], ondelete='CASCADE',
    )

    # Excluir um número tira ele da rotação de qualquer faixa que o usava.
    op.drop_constraint(
        'faixa_numbers_whatsapp_number_id_fkey', 'faixa_numbers', type_='foreignkey'
    )
    op.create_foreign_key(
        'faixa_numbers_whatsapp_number_id_fkey',
        'faixa_numbers', 'whatsapp_numbers', ['whatsapp_number_id'], ['id'], ondelete='CASCADE',
    )

    # Excluir um número preserva o histórico de envio (cobranca_fila), só
    # perde a referência de qual número específico mandou.
    op.drop_constraint(
        'cobranca_fila_whatsapp_number_id_fkey', 'cobranca_fila', type_='foreignkey'
    )
    op.create_foreign_key(
        'cobranca_fila_whatsapp_number_id_fkey',
        'cobranca_fila', 'whatsapp_numbers', ['whatsapp_number_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'cobranca_fila_whatsapp_number_id_fkey', 'cobranca_fila', type_='foreignkey'
    )
    op.create_foreign_key(
        'cobranca_fila_whatsapp_number_id_fkey',
        'cobranca_fila', 'whatsapp_numbers', ['whatsapp_number_id'], ['id'],
    )

    op.drop_constraint(
        'faixa_numbers_whatsapp_number_id_fkey', 'faixa_numbers', type_='foreignkey'
    )
    op.create_foreign_key(
        'faixa_numbers_whatsapp_number_id_fkey',
        'faixa_numbers', 'whatsapp_numbers', ['whatsapp_number_id'], ['id'],
    )

    op.drop_constraint(
        'fk_whatsapp_numbers_meta_token_id_meta_tokens', 'whatsapp_numbers', type_='foreignkey'
    )
    op.create_foreign_key(
        'fk_whatsapp_numbers_meta_token_id_meta_tokens',
        'whatsapp_numbers', 'meta_tokens', ['meta_token_id'], ['id'], ondelete='SET NULL',
    )
