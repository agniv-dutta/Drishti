"""Create voice recovery call log schema.

Revision ID: 20260905_voice_recovery
Revises: 20260905_mandate_recovery
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260905_voice_recovery"
down_revision = "20260905_mandate_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_call_logs",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("payment_id", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False, server_default="en"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="initiated"),
        sa.Column("script", sa.JSON(), nullable=False),
        sa.Column("recording_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("customer_choice", sa.String(length=8), nullable=True),
        sa.Column("action_taken", sa.String(length=24), nullable=True),
        sa.Column("action_message", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recording_url", sa.String(length=512), nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.UniqueConstraint("call_id"),
    )
    op.create_index("ix_voice_call_logs_call_id", "voice_call_logs", ["call_id"])
    op.create_index("ix_voice_call_logs_payment", "voice_call_logs", ["payment_id"])
    op.create_index("ix_voice_call_logs_status", "voice_call_logs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_voice_call_logs_status", table_name="voice_call_logs")
    op.drop_index("ix_voice_call_logs_payment", table_name="voice_call_logs")
    op.drop_index("ix_voice_call_logs_call_id", table_name="voice_call_logs")
    op.drop_table("voice_call_logs")