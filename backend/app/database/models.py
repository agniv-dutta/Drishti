"""SQLAlchemy ORM models mirroring the Pydantic domain models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    BigInteger,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.payment import (
    CustomerInfo,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
    Retryability,
    utcnow,
)
from app.models.recovery import (
    ExecutionResult,
    FailureAnalysis,
    RecoveryPlan,
    RecoveryStatus,
    RecoveryStrategy,
)
from app.models.audit import AuditEventType, AuditSeverity


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class PaymentRecord(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    gateway_payment_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    customer_name: Mapped[str] = mapped_column(String(120))
    customer_email_masked: Mapped[str] = mapped_column(String(160))
    customer_contact_encrypted: Mapped[str] = mapped_column(Text)  # Fernet({email, phone})

    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=PaymentStatus.CREATED.value, index=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_description: Mapped[Optional[str]] = mapped_column(Text)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)

    risk_score: Mapped[Optional[float]] = mapped_column(Float)
    risk_band: Mapped[Optional[str]] = mapped_column(String(16))

    meta: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # ------------------------------------------------------------------
    @classmethod
    def from_domain(cls, txn: PaymentTransaction, contact_encrypted: str) -> "PaymentRecord":
        from app.utils.formatters import mask_email  # local import avoids cycles

        reason = txn.failure_reason.value if txn.failure_reason else None
        if isinstance(txn.failure_reason, str):
            reason = txn.failure_reason
        method = txn.method.value if isinstance(txn.method, PaymentMethod) else str(txn.method)
        status = txn.status.value if isinstance(txn.status, PaymentStatus) else str(txn.status)

        return cls(
            id=txn.payment_id,
            order_id=txn.order_id,
            gateway_payment_id=txn.gateway_payment_id,
            customer_name=txn.customer.name,
            customer_email_masked=mask_email(txn.customer.email),
            customer_contact_encrypted=contact_encrypted,
            amount_paise=txn.amount_paise,
            currency=txn.currency,
            method=method,
            status=status,
            failure_reason=reason,
            error_code=txn.error_code,
            error_description=txn.error_description,
            attempt_number=txn.attempt_number,
            meta=txn.meta,
            created_at=txn.created_at,
        )

    def to_domain(self) -> PaymentTransaction:
        """Rehydrate a PaymentTransaction (decrypts customer contact)."""
        from app.utils.encryption import decrypt_dict

        contact = decrypt_dict(self.customer_contact_encrypted)
        return PaymentTransaction(
            payment_id=self.id,
            order_id=self.order_id,
            gateway_payment_id=self.gateway_payment_id,
            customer=CustomerInfo(
                name=self.customer_name,
                email=contact.get("email", ""),
                phone=contact.get("phone", ""),
            ),
            amount_paise=self.amount_paise,
            currency=self.currency,
            method=self.method,
            status=self.status,
            failure_reason=(
                FailureReason(self.failure_reason) if self.failure_reason else None
            ),
            error_code=self.error_code,
            error_description=self.error_description,
            attempt_number=self.attempt_number,
            meta=self.meta or {},
            created_at=self.created_at,
        )

    def public_view(self) -> Dict[str, Any]:
        """PII-safe projection used by API responses."""
        return {
            "payment_id": self.id,
            "order_id": self.order_id,
            "gateway_payment_id": self.gateway_payment_id,
            "customer_name": self.customer_name,
            "customer_email": self.customer_email_masked,
            "amount_inr": round(self.amount_paise / 100, 2),
            "currency": self.currency,
            "method": self.method,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "error_code": self.error_code,
            "attempt_number": self.attempt_number,
            "risk_score": self.risk_score,
            "risk_band": self.risk_band,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Recoveries
# ---------------------------------------------------------------------------

class RecoveryRecord(Base):
    __tablename__ = "recoveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)

    strategy: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(20), default=RecoveryStatus.PENDING.value, index=True
    )
    priority: Mapped[str] = mapped_column(String(2), default="P2")

    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    expected_amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    recovered_amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_paise: Mapped[int] = mapped_column(Integer, default=0)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)

    analysis_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    plan_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    result_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    def save_plan(self, plan: RecoveryPlan) -> None:
        self.plan_json = plan.model_dump(mode="json")
        self.strategy = (
            plan.strategy.value if isinstance(plan.strategy, RecoveryStrategy) else str(plan.strategy)
        )
        self.status = RecoveryStatus.PLANNED.value

    def apply_result(self, result: ExecutionResult) -> None:
        self.result_json = result.model_dump(mode="json")
        self.cost_paise += result.total_cost_paise
        self.recovered_amount_paise += result.recovered_amount_paise
        self.attempts += len([o for o in result.outcomes if o.status.value != "skipped"])
        self.executed_at = result.completed_at
        if result.success:
            self.status = RecoveryStatus.SUCCEEDED.value
            self.completed_at = result.completed_at
        elif self.attempts >= self.max_attempts:
            self.status = RecoveryStatus.EXHAUSTED.value
            self.completed_at = result.completed_at
        else:
            self.status = RecoveryStatus.FAILED.value


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class AuditRecord(Base):
    __tablename__ = "audits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10), default=AuditSeverity.INFO.value)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    is_exception: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    @classmethod
    def from_entry(cls, entry) -> "AuditRecord":
        """Build from an ``AuditLogEntry`` domain model."""
        event_type = entry.event_type.value if isinstance(entry.event_type, AuditEventType) else entry.event_type
        severity = entry.severity.value if isinstance(entry.severity, AuditSeverity) else str(entry.severity)
        return cls(
            id=entry.event_id,
            timestamp=entry.timestamp,
            event_type=event_type,
            severity=severity,
            actor=entry.actor,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            outcome=entry.outcome,
            message=entry.message,
            details=entry.details,
            is_exception=entry.is_exception or severity == AuditSeverity.CRITICAL.value,
        )
