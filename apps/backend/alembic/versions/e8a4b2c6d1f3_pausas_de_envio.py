"""pausas de envio por cliente, faixa ou loja; lojas no item da fila; status cancelado

Revision ID: e8a4b2c6d1f3
Revises: d7e3f9a2b5c4
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

revision = "e8a4b2c6d1f3"
down_revision = "d7e3f9a2b5c4"
branch_labels = None
depends_on = None

_STATUS_ANTIGOS = ("pending", "reserved", "sent", "error", "invalid_phone")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ADD VALUE fora da transação: o valor novo não pode ser usado na
        # mesma transação em que foi criado.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE queuestatus ADD VALUE IF NOT EXISTS 'cancelled'")

    op.add_column("cobranca_fila", sa.Column("lojas", sa.String(), server_default=",", nullable=False))

    op.create_table(
        "pausas_envio",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("escopo", sa.String(), nullable=False),
        sa.Column("valor", sa.String(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("ate", sa.Date(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("encerrada_em", sa.DateTime(), nullable=True),
        sa.Column("encerrada_por", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pausas_envio_escopo"), "pausas_envio", ["escopo"], unique=False)
    op.create_index(op.f("ix_pausas_envio_encerrada_em"), "pausas_envio", ["encerrada_em"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pausas_envio_encerrada_em"), table_name="pausas_envio")
    op.drop_index(op.f("ix_pausas_envio_escopo"), table_name="pausas_envio")
    op.drop_table("pausas_envio")
    op.drop_column("cobranca_fila", "lojas")

    bind = op.get_bind()
    # Postgres não remove valor de ENUM: parado vira erro (a mensagem de quem
    # parou fica em error_message) e o tipo é recriado sem 'cancelled'.
    op.execute("UPDATE cobranca_fila SET status = 'error' WHERE status = 'cancelled'")
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE queuestatus RENAME TO queuestatus_old")
        sa.Enum(*_STATUS_ANTIGOS, name="queuestatus").create(bind)
        op.execute(
            "ALTER TABLE cobranca_fila ALTER COLUMN status TYPE queuestatus USING status::text::queuestatus"
        )
        op.execute("DROP TYPE queuestatus_old")
