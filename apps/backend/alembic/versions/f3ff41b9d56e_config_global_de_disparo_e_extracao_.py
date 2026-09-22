"""config global de disparo e extracao automatica de leads

Revision ID: f3ff41b9d56e
Revises: 02887e88dfea
Create Date: 2026-09-22 23:29:23.789720

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3ff41b9d56e'
down_revision: Union[str, None] = '02887e88dfea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('global_dispatch_config',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('schedule_days', sa.String(), nullable=False),
    sa.Column('schedule_start', sa.String(), nullable=False),
    sa.Column('schedule_end', sa.String(), nullable=False),
    sa.Column('leads_auto_extract', sa.Boolean(), nullable=False),
    sa.Column('leads_auto_extract_minutos_antes', sa.Integer(), nullable=False),
    sa.Column('leads_auto_extract_last_run', sa.Date(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # Linha única (singleton) com os valores padrão que antes ficavam em cada
    # dispatch_configs.schedule_* — preserva o comportamento default anterior.
    op.execute(
        "INSERT INTO global_dispatch_config "
        "(id, schedule_days, schedule_start, schedule_end, leads_auto_extract, leads_auto_extract_minutos_antes) "
        "VALUES ('global', '1,2,3,4,5', '08:00', '18:30', false, 15)"
    )
    op.drop_column('dispatch_configs', 'schedule_start')
    op.drop_column('dispatch_configs', 'schedule_end')
    op.drop_column('dispatch_configs', 'schedule_days')


def downgrade() -> None:
    op.add_column(
        'dispatch_configs',
        sa.Column('schedule_days', sa.VARCHAR(), nullable=False, server_default='1,2,3,4,5'),
    )
    op.add_column(
        'dispatch_configs',
        sa.Column('schedule_end', sa.VARCHAR(), nullable=False, server_default='18:30'),
    )
    op.add_column(
        'dispatch_configs',
        sa.Column('schedule_start', sa.VARCHAR(), nullable=False, server_default='08:00'),
    )
    op.alter_column('dispatch_configs', 'schedule_days', server_default=None)
    op.alter_column('dispatch_configs', 'schedule_end', server_default=None)
    op.alter_column('dispatch_configs', 'schedule_start', server_default=None)
    op.drop_table('global_dispatch_config')
