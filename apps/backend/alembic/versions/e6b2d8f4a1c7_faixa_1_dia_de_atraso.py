"""faixa de atraso "1" (1 dia) na régua

Revision ID: e6b2d8f4a1c7
Revises: d4f7a2c9e1b5
Create Date: 2026-10-08

Onde nenhuma faixa de atraso cobre 1 dia (ex.: "-1" só com -1 e "2" só com 2),
o cliente com 1 dia de atraso não aparecia em faixa nenhuma. Cria a faixa de
atraso "1" (de 1 a 1 dia) e a faixa de cobrança da régua com o mesmo nome, sem
envio (número e template) e fora da matriz do WhatsApp, como faz o
"Sincronizar faixas". Onde o dia 1 já está numa faixa (padrão "-1" de -1 a 1),
não muda nada.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e6b2d8f4a1c7"
down_revision: str | None = "d4f7a2c9e1b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOME = "1"


def upgrade() -> None:
    bind = op.get_bind()
    if not bind.execute(sa.text("SELECT 1 FROM config_faixas_atraso")).first():
        return  # sem regras cadastradas: nada a completar
    cobre = bind.execute(
        sa.text(
            "SELECT 1 FROM config_faixas_atraso "
            "WHERE nome = :n OR (dia_min <= 1 AND (dia_max IS NULL OR dia_max >= 1))"
        ),
        {"n": NOME},
    ).first()
    if cobre:
        return
    bind.execute(
        sa.text(
            "INSERT INTO config_faixas_atraso (id, nome, dia_min, dia_max, so_campanhas) "
            "VALUES (:id, :nome, 1, 1, false)"
        ),
        {"id": str(uuid.uuid4()), "nome": NOME},
    )
    if not bind.execute(sa.text("SELECT 1 FROM faixas WHERE name = :n"), {"n": NOME}).first():
        bind.execute(
            sa.text(
                "INSERT INTO faixas (id, name, active, upload_field_mapping, created_at, tipo) "
                "VALUES (:id, :nome, true, '{}', now(), 'regua')"
            ),
            {"id": str(uuid.uuid4()), "nome": NOME},
        )


def downgrade() -> None:
    # Só desfaz o que ficou sem uso: faixa com fila, envio ou planilha fica.
    op.execute(
        "DELETE FROM faixas WHERE name = '1' AND tipo = 'regua' "
        "AND NOT EXISTS (SELECT 1 FROM cobranca_fila q WHERE q.faixa_id = faixas.id) "
        "AND NOT EXISTS (SELECT 1 FROM faixa_envios e WHERE e.faixa_id = faixas.id) "
        "AND NOT EXISTS (SELECT 1 FROM upload_logs u WHERE u.faixa_id = faixas.id)"
    )
    op.execute(
        "DELETE FROM config_regras_whatsapp WHERE faixa_id IN "
        "(SELECT id FROM config_faixas_atraso WHERE nome = '1' AND dia_min = 1 AND dia_max = 1)"
    )
    op.execute("DELETE FROM config_faixas_atraso WHERE nome = '1' AND dia_min = 1 AND dia_max = 1")
