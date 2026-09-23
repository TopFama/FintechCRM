"""remove a variável "Valor a cobrar": o que sobrou passa para "Valor em atraso"

A opção "valor_cobrar" saiu do catálogo de campos do cliente. Qualquer
mapeamento, expressão ou sugestão que ainda aponte para ela passa para
"valor_atraso" — senão o envio falharia com placeholder desconhecido.

Revision ID: b8c4d0e3f5a2
Revises: a7b3c9d2e4f1
Create Date: 2026-09-23
"""

from alembic import op

revision = "b8c4d0e3f5a2"
down_revision = "a7b3c9d2e4f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE faixa_variable_mappings SET column_name = 'valor_atraso' "
        "WHERE fonte_tipo = 'campo_cliente' AND column_name = 'valor_cobrar'"
    )
    op.execute(
        "UPDATE faixa_variable_mappings SET expressao = regexp_replace("
        "expressao, '\\{\\s*(valor_cobrar|valor a cobrar)\\s*\\}', '{valor_atraso}', 'gi') "
        "WHERE fonte_tipo = 'expressao' AND expressao ~* '\\{\\s*(valor_cobrar|valor a cobrar)\\s*\\}'"
    )
    op.execute("UPDATE template_variables SET campo_sugerido = 'valor_atraso' WHERE campo_sugerido = 'valor_cobrar'")


def downgrade() -> None:
    # Irreversível: não dá pra distinguir o que já era "valor_atraso" antes.
    pass
