"""Create mandate recovery schema.

Revision ID: 20260905_mandate_recovery
Revises: 20260822_verity_schema
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260905_mandate_recovery"
down_revision = "20260822_verity_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mandates",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("retry_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("failure_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promised_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mandates_merchant_id", "mandates", ["merchant_id"])
    op.create_index("ix_mandates_merchant_status", "mandates", ["merchant_id", "status"])
    op.create_index("ix_mandates_failure_date", "mandates", ["failure_date"])
    op.create_index("ix_mandates_status", "mandates", ["status"])

    op.create_table(
        "mandate_retries",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("mandate_id", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.id"]),
    )
    op.create_index("ix_mandate_retries_mandate_id", "mandate_retries", ["mandate_id"])


def downgrade() -> None:
    op.drop_index("ix_mandate_retries_mandate_id", table_name="mandate_retries")
    op.drop_table("mandate_retries")
    op.drop_index("ix_mandates_status", table_name="mandates")
    op.drop_index("ix_mandates_failure_date", table_name="mandates")
    op.drop_index("ix_mandates_merchant_status", table_name="mandates")
    op.drop_index("ix_mandates_merchant_id", table_name="mandates")
    op.drop_table("mandates")