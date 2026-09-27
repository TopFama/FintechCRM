"""cópia de pagamentos só com títulos do crediário (tipo 4 e 5)

A leitura do SETA passou a ignorar venda à vista e o registro de quitação do
lote (PayHub, BAIXA DE TITULO), que repetia a soma das parcelas e dobrava o
valor pago. A marca d'água volta para o início de cada cliente: a próxima
rodada relê tudo e troca as baixas copiadas pelas do filtro novo.

Revision ID: c6e0a4b8d2f5
Revises: b4d8f2a6c0e3
Create Date: 2026-09-26
"""

from alembic import op

revision = "c6e0a4b8d2f5"
down_revision = "b4d8f2a6c0e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE pagamentos_seta_clientes SET marca_dagua = desde")


def downgrade() -> None:
    pass
