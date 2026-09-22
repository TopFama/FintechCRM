"""cobranca_fila: trocar codigo_tipo por cpf obrigatorio

Revision ID: 9137e403d92d
Revises: 3bd1d89aa92f
Create Date: 2026-09-21 22:48:44.622285

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9137e403d92d'
down_revision: Union[str, None] = '3bd1d89aa92f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default só pra preencher as linhas já existentes — removido logo
    # em seguida, já que o código sempre informa cpf explicitamente daqui pra
    # frente (mesmo padrão do resto da tabela, sem default no ORM).
    op.add_column('cobranca_fila', sa.Column('cpf', sa.String(), nullable=False, server_default=''))
    op.alter_column('cobranca_fila', 'cpf', server_default=None)
    op.drop_column('cobranca_fila', 'codigo_tipo')


def downgrade() -> None:
    op.add_column(
        'cobranca_fila',
        sa.Column('codigo_tipo', sa.VARCHAR(), autoincrement=False, nullable=False, server_default='seta'),
    )
    op.alter_column('cobranca_fila', 'codigo_tipo', server_default=None)
    op.drop_column('cobranca_fila', 'cpf')
