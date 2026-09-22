"""template da faixa opcional

Faixas sincronizadas a partir das faixas de atraso (config de cobrança)
nascem sem template atribuído — o disparo fica pausado até alguém
completar a configuração em "Faixas de cobrança".

Revision ID: f1a2b3c4d5e6
Revises: 2bb816634f94
Create Date: 2026-09-22 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '2bb816634f94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('faixas', 'template_id', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Faixas sem template não podem virar NOT NULL sem um valor — atribui o
    # primeiro template existente só pra permitir o downgrade em bases de
    # teste; em produção não deveria haver faixa sem template ao reverter.
    conn = op.get_bind()
    algum_template = conn.execute(sa.text("SELECT id FROM templates LIMIT 1")).scalar()
    if algum_template is not None:
        conn.execute(
            sa.text("UPDATE faixas SET template_id = :tid WHERE template_id IS NULL"),
            {"tid": algum_template},
        )
    else:
        conn.execute(sa.text("DELETE FROM faixas WHERE template_id IS NULL"))
    op.alter_column('faixas', 'template_id', existing_type=sa.String(), nullable=False)
