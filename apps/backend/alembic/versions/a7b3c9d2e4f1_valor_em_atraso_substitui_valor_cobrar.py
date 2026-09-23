"""variáveis de valor passam a usar "Valor em atraso"

Mapeamentos de faixa e sugestões de template que usavam o campo do cliente
"valor_cobrar" (Valor a cobrar) passam para "valor_atraso" (Valor em atraso,
com juros e multa corridos até o dia do envio).

Revision ID: a7b3c9d2e4f1
Revises: 7c1e2a9d4b10
Create Date: 2026-09-23
"""

from alembic import op

revision = "a7b3c9d2e4f1"
down_revision = "7c1e2a9d4b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE faixa_variable_mappings SET column_name = 'valor_atraso' "
        "WHERE fonte_tipo = 'campo_cliente' AND column_name = 'valor_cobrar'"
    )
    op.execute("UPDATE template_variables SET campo_sugerido = 'valor_atraso' WHERE campo_sugerido = 'valor_cobrar'")


def downgrade() -> None:
    # Não dá pra saber quais já eram "valor_atraso" antes; volta todos.
    op.execute(
        "UPDATE faixa_variable_mappings SET column_name = 'valor_cobrar' "
        "WHERE fonte_tipo = 'campo_cliente' AND column_name = 'valor_atraso'"
    )
    op.execute("UPDATE template_variables SET campo_sugerido = 'valor_cobrar' WHERE campo_sugerido = 'valor_atraso'")
