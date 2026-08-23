"""Human triage queue: ticket creation, customer profiles, serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.database.models import PaymentRecord, TriageTicketRecord, utcnow
from app.models.payment import PaymentTransaction
from app.models.recovery import RecoveryPlan
from app.routing.confidence_router import RoutingDecision


logger = get_logger("drishti.triage")


def customer_profile(db: Session, payment: PaymentRecord) -> Dict[str, Any]:
    """Aggregate this customer's history from prior payments (masked email key)."""
    rows = (
        db.query(PaymentRecord)
        .filter(PaymentRecord.customer_email_masked == payment.customer_email_masked)
        .all()
    )
    total = len(rows)
    failed = sum(1 for r in rows if r.status == "failed")
    ltv_paise = sum(r.amount_paise for r in rows if r.status == "succeeded")
    return {
        "total_payments": total,
        "failed_payments": failed,
        "successful_payments": total - failed,
        "ltv_paise": ltv_paise,
        "is_new_customer": total <= 1,
    }


def create_triage_ticket(
    db: Session,
    payment: PaymentRecord,
    plan: RecoveryPlan,
    decision: RoutingDecision,
) -> TriageTicketRecord:
    """Open a queue entry (idempotent per payment - one open ticket max)."""
    existing = (
        db.query(TriageTicketRecord)
        .filter(
            TriageTicketRecord.payment_id == payment.id,
            TriageTicketRecord.status == "open",
        )
        .first()
    )
    if existing is not None:
        return existing

    strategy = plan.strategy.value if hasattr(plan.strategy, "value") else str(plan.strategy)
    history = customer_profile(db, payment)
    # Per-payment priority (the decision's score is just the routing hint):
    # high-value first, new customers second.
    amount_component = min((payment.amount_paise / 100) / 100_000.0, 10.0) * 10.0
    priority = amount_component + (0.0 if history["is_new_customer"] else 5.0)

    ticket = TriageTicketRecord(
        payment_id=payment.id,
        recovery_id=None,
        failure_reason=payment.failure_reason,
        recommended_strategy=strategy,
        confidence=float(plan.expected_success_probability),
        customer_name=payment.customer_name,
        customer_email_masked=payment.customer_email_masked,
        amount_paise=payment.amount_paise,
        customer_history=history,
        low_confidence_reasons=list(decision.reasons),
        priority_score=priority,
        status="open",
    )
    db.add(ticket)
    db.flush()
    logger.info(
        "triage.ticket_created",
        ticket_id=ticket.id,
        payment_id=payment.id,
        priority=round(ticket.priority_score, 1),
    )
    return ticket


def list_open_tickets(db: Session) -> List[TriageTicketRecord]:
    """Priority order: high-value first, new customers second, oldest first on ties."""
    return (
        db.query(TriageTicketRecord)
        .filter(TriageTicketRecord.status == "open")
        .order_by(TriageTicketRecord.priority_score.desc(), TriageTicketRecord.created_at.asc())
        .all()
    )


def ticket_to_dict(ticket: TriageTicketRecord) -> Dict[str, Any]:
    return {
        "ticket_id": ticket.id,
        "status": ticket.status,
        "payment_id": ticket.payment_id,
        "failure_reason": ticket.failure_reason,
        "recommended_strategy": ticket.recommended_strategy,
        "confidence": round(float(ticket.confidence), 4),
        "amount_paise": int(ticket.amount_paise),
        "customer_name": ticket.customer_name,
        "customer_email_masked": ticket.customer_email_masked,
        "customer_history": ticket.customer_history or {},
        "low_confidence_reasons": list(ticket.low_confidence_reasons or []),
        "priority_score": round(float(ticket.priority_score), 2),
        "overridden_strategy": ticket.overridden_strategy,
        "custom_message": ticket.custom_message,
        "resolution_note": ticket.resolution_note,
        "resolved_by": ticket.resolved_by,
        "resolved_at": _iso(ticket.resolved_at),
        "created_at": _iso(ticket.created_at),
    }


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
