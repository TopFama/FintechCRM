"""tabela lojas (base de lojas com cluster de cobradora)

Revision ID: a7c3e9d1f4b6
Revises: b8c4d0e3f5a2
Create Date: 2026-09-24 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a7c3e9d1f4b6'
down_revision: Union[str, None] = 'b8c4d0e3f5a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lojas',
        sa.Column('filial', sa.String(length=4), nullable=False),
        sa.Column('nome_com_cod', sa.String(), nullable=True),
        sa.Column('regional', sa.String(), nullable=True),
        sa.Column('estado', sa.String(length=2), nullable=True),
        sa.Column('cluster_cobradora', sa.String(), nullable=True),
        sa.Column('cluster_inad', sa.String(), nullable=True),
        sa.Column('cluster_populacao', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('filial'),
    )


def downgrade() -> None:
    op.drop_table('lojas')
