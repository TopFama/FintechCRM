"""horário do caixa na cópia local das baixas do SETA

`pago_em` guarda o horário do recebimento no caixa da loja, quando existe,
pra não contar como efeito da cobrança um pagamento feito no mesmo dia antes
da mensagem. A marca d'água volta para o início de cada cliente: a próxima
rodada relê tudo e preenche o horário das baixas já copiadas.

Revision ID: a3c7e1f5b9d2
Revises: f6b1d3a8c2e4
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

revision = "a3c7e1f5b9d2"
down_revision = "f6b1d3a8c2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pagamentos_seta", sa.Column("pago_em", sa.DateTime(), nullable=True))
    op.execute("UPDATE pagamentos_seta_clientes SET marca_dagua = desde")


def downgrade() -> None:
    op.drop_column("pagamentos_seta", "pago_em")
