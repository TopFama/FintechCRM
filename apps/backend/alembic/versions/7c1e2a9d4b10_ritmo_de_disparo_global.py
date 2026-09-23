"""ritmo de disparo (intervalo e quantidade por vez) global

Revision ID: 7c1e2a9d4b10
Revises: 6969f017649b
Create Date: 2026-09-23 10:30:00
"""
from alembic import op
import sqlalchemy as sa

revision = "7c1e2a9d4b10"
down_revision = "6969f017649b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("global_dispatch_config", sa.Column("interval_seconds", sa.Integer(), server_default="5", nullable=False))
    op.add_column("global_dispatch_config", sa.Column("batch_size", sa.Integer(), server_default="3", nullable=False))


def downgrade() -> None:
    op.drop_column("global_dispatch_config", "batch_size")
    op.drop_column("global_dispatch_config", "interval_seconds")
