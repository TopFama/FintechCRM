"""remarketing de clientes do Renegocie

Revision ID: c5d2e8f1a9b3
Revises: a7c3e9d1f4b6
Create Date: 2026-09-24 03:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c5d2e8f1a9b3'
down_revision: Union[str, None] = 'a7c3e9d1f4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'integracao_renegocie',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('base_url', sa.String(), nullable=False),
        sa.Column('chave_cifrada', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'remarketing_segmentos',
        sa.Column('segmento', sa.String(), primary_key=True),
        sa.Column('faixa_id', sa.String(), sa.ForeignKey('faixas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('janela_dias', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('recontato_dias', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('cobradoras', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('faixas_atraso', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('clusters', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('valor_min', sa.Numeric(14, 2), nullable=True),
        sa.Column('valor_max', sa.Numeric(14, 2), nullable=True),
        sa.Column('ultima_execucao', sa.DateTime(), nullable=True),
        sa.Column('ultimo_resultado', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.add_column('global_dispatch_config', sa.Column('remarketing_last_run', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('global_dispatch_config', 'remarketing_last_run')
    op.drop_table('remarketing_segmentos')
    op.drop_table('integracao_renegocie')
