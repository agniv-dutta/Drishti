"""Create Verity revenue recovery schema.

Revision ID: 20260822_verity_schema
Revises: None
Create Date: 2026-08-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_verity_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("api_key_hash", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint("api_key_hash", name="uq_merchants_api_key_hash"),
    )

    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(length=32), nullable=False),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
    )
    op.create_index(
        "ix_payment_transactions_merchant_id",
        "payment_transactions",
        ["merchant_id"],
    )
    op.create_index(
        "ix_payment_transactions_status",
        "payment_transactions",
        ["status"],
    )
    op.create_index(
        "ix_payment_transactions_created_at",
        "payment_transactions",
        ["created_at"],
    )

    op.create_table(
        "recovery_attempts",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("payment_id", sa.String(length=32), nullable=False),
        sa.Column("strategy_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("intervention_channel", sa.String(length=64), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("money_recovered", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payment_transactions.id"]),
    )
    op.create_index(
        "ix_recovery_attempts_payment_id",
        "recovery_attempts",
        ["payment_id"],
    )
    op.create_index(
        "ix_recovery_attempts_status",
        "recovery_attempts",
        ["status"],
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=False),
        sa.Column("model_confidence", sa.Float(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
    )
    op.create_index(
        "ix_audit_logs_merchant_id",
        "audit_logs",
        ["merchant_id"],
    )
    op.create_index(
        "ix_audit_logs_timestamp",
        "audit_logs",
        ["timestamp"],
    )

    op.create_table(
        "ml_model_versions",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("f1_score", sa.Float(), nullable=True),
        sa.Column(
            "training_date",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )

    op.create_table(
        "recovery_workflows",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("template_name", sa.String(length=128), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint("template_name", name="uq_recovery_workflows_template_name"),
    )


def downgrade() -> None:
    op.drop_table("recovery_workflows")
    op.drop_table("ml_model_versions")

    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_merchant_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_recovery_attempts_status", table_name="recovery_attempts")
    op.drop_index("ix_recovery_attempts_payment_id", table_name="recovery_attempts")
    op.drop_table("recovery_attempts")

    op.drop_index("ix_payment_transactions_created_at", table_name="payment_transactions")
    op.drop_index("ix_payment_transactions_status", table_name="payment_transactions")
    op.drop_index("ix_payment_transactions_merchant_id", table_name="payment_transactions")
    op.drop_table("payment_transactions")

    op.drop_table("merchants")
