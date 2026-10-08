"""faixa de atraso só de campanhas e a faixa "Antecipado"

Revision ID: c8e2a4f6b0d1
Revises: b5e9d3a7c1f4
Create Date: 2026-10-08

"Antecipado" = clientes cuja parcela aberta mais antiga ainda vai vencer,
antes da primeira faixa configurada (padrão "-1"): de -365 até o dia anterior
a ela. Só aparece em Campanhas.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c8e2a4f6b0d1"
down_revision: str | None = "b5e9d3a7c1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOME = "Antecipado"
DIA_MIN = -365


def upgrade() -> None:
    op.add_column(
        "config_faixas_atraso", sa.Column("so_campanhas", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM config_faixas_atraso WHERE nome = :n"), {"n": NOME}).first():
        return
    primeiro = bind.execute(sa.text("SELECT min(dia_min) FROM config_faixas_atraso")).scalar()
    dia_max = -2 if primeiro is None else min(-2, primeiro - 1)
    if dia_max < DIA_MIN:
        return
    bind.execute(
        sa.text(
            "INSERT INTO config_faixas_atraso (id, nome, dia_min, dia_max, so_campanhas) "
            "VALUES (:id, :nome, :dia_min, :dia_max, true)"
        ),
        {"id": str(uuid.uuid4()), "nome": NOME, "dia_min": DIA_MIN, "dia_max": dia_max},
    )


def downgrade() -> None:
    op.execute("DELETE FROM config_faixas_atraso WHERE so_campanhas")
    op.drop_column("config_faixas_atraso", "so_campanhas")
