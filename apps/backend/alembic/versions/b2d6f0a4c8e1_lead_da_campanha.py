"""lead marca a campanha que enviou (filtro na Efetividade e na exportação)

Revision ID: b2d6f0a4c8e1
Revises: a7c1e5d9b3f2
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "b2d6f0a4c8e1"
down_revision = "a7c1e5d9b3f2"
branch_labels = None
depends_on = None

_COLUNAS = ["codigo_cliente", "faixa", "vencimento_mais_antigo"]


def _unique_antiga() -> str | None:
    for uc in sa.inspect(op.get_bind()).get_unique_constraints("leads"):
        if sorted(uc["column_names"]) == sorted(_COLUNAS):
            return uc["name"]
    return None


def upgrade() -> None:
    op.add_column("leads", sa.Column("campanha_id", sa.String(), server_default="", nullable=False))
    op.add_column("leads", sa.Column("regua_em", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_leads_campanha_id"), "leads", ["campanha_id"], unique=False)
    antiga = _unique_antiga()
    if antiga:
        op.drop_constraint(antiga, "leads", type_="unique")
    op.create_unique_constraint("uq_leads_cliente_faixa_parcela", "leads", [*_COLUNAS, "campanha_id"])


def downgrade() -> None:
    # Leads de campanha somem: sem a coluna, colidiriam com os da régua.
    op.execute("DELETE FROM lead_parcelas WHERE lead_id IN (SELECT id FROM leads WHERE campanha_id <> '')")
    op.execute("DELETE FROM leads WHERE campanha_id <> ''")
    op.drop_constraint("uq_leads_cliente_faixa_parcela", "leads", type_="unique")
    op.create_unique_constraint("leads_codigo_cliente_faixa_vencimento_mais_antigo_key", "leads", _COLUNAS)
    op.drop_index(op.f("ix_leads_campanha_id"), table_name="leads")
    op.drop_column("leads", "regua_em")
    op.drop_column("leads", "campanha_id")
