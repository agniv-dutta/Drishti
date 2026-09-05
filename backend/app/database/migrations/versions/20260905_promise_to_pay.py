"""Create promise-to-pay commitment schema.

Revision ID: 20260905_promise_to_pay
Revises: 20260905_voice_recovery
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260905_promise_to_pay"
down_revision = "20260905_voice_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promise_to_pay",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("payment_id", sa.String(length=32), nullable=False),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("promised_amount", sa.Float(), nullable=False),
        sa.Column("promised_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("paid_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
    )
    op.create_index("ix_promise_to_pay_id", "promise_to_pay", ["id"])
    op.create_index("ix_promise_to_pay_payment_id", "promise_to_pay", ["payment_id"])
    op.create_index("ix_promise_to_pay_merchant_id", "promise_to_pay", ["merchant_id"])
    op.create_index("ix_promise_to_pay_customer_id", "promise_to_pay", ["customer_id"])
    op.create_index("ix_promise_to_pay_promised_date", "promise_to_pay", ["promised_date"])
    op.create_index("ix_promise_to_pay_status", "promise_to_pay", ["status"])
    op.create_index("ix_promise_to_pay_merchant_status", "promise_to_pay", ["merchant_id", "status"])

    op.create_table(
        "promise_to_pay_tasks",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("promise_id", sa.String(length=32), nullable=False),
        sa.Column("payment_id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["promise_id"], ["promise_to_pay.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
    )
    op.create_index("ix_promise_to_pay_tasks_promise_id", "promise_to_pay_tasks", ["promise_id"])
    op.create_index("ix_promise_to_pay_tasks_payment_id", "promise_to_pay_tasks", ["payment_id"])
    op.create_index("ix_promise_to_pay_tasks_task_type", "promise_to_pay_tasks", ["task_type"])
    op.create_index("ix_promise_to_pay_tasks_scheduled_for", "promise_to_pay_tasks", ["scheduled_for"])
    op.create_index("ix_promise_to_pay_tasks_status", "promise_to_pay_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_promise_to_pay_tasks_status", table_name="promise_to_pay_tasks")
    op.drop_index("ix_promise_to_pay_tasks_scheduled_for", table_name="promise_to_pay_tasks")
    op.drop_index("ix_promise_to_pay_tasks_task_type", table_name="promise_to_pay_tasks")
    op.drop_index("ix_promise_to_pay_tasks_payment_id", table_name="promise_to_pay_tasks")
    op.drop_index("ix_promise_to_pay_tasks_promise_id", table_name="promise_to_pay_tasks")
    op.drop_table("promise_to_pay_tasks")
    op.drop_index("ix_promise_to_pay_merchant_status", table_name="promise_to_pay")
    op.drop_index("ix_promise_to_pay_status", table_name="promise_to_pay")
    op.drop_index("ix_promise_to_pay_promised_date", table_name="promise_to_pay")
    op.drop_index("ix_promise_to_pay_customer_id", table_name="promise_to_pay")
    op.drop_index("ix_promise_to_pay_merchant_id", table_name="promise_to_pay")
    op.drop_index("ix_promise_to_pay_payment_id", table_name="promise_to_pay")
    op.drop_index("ix_promise_to_pay_id", table_name="promise_to_pay")
    op.drop_table("promise_to_pay")