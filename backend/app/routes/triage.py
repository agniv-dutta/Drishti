"""Human triage queue + customer consent endpoints.

Triage (API-key protected):
    GET  /api/v1/triage/queue                 priority-ordered open tickets
    POST /api/v1/triage/{id}/override         agent overrides strategy/message
    POST /api/v1/triage/{id}/resolve          agent closes the ticket

Consent (public - customers answer from their phone):
    POST /api/v1/triage/consent/respond       YES -> chatbot handoff / NO -> defer 72h
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import get_supervisor
from app.agents.supervisor_agent import PaymentNotFoundError
from app.core.config import get_settings
from app.core.security import require_api_key
from app.database.models import ConsentRequestRecord, TriageTicketRecord, utcnow
from app.database.session import get_db
from app.models.audit import AuditEventType, AuditSeverity
from app.models.recovery import RecoveryStrategy
from app.routing import triage_service


router = APIRouter(prefix="/triage", tags=["triage"], dependencies=[Depends(require_api_key)])
# Customer-facing consent answers arrive from phones/webhooks - no API key.
public_router = APIRouter(prefix="/triage/consent", tags=["triage"])


class OverrideRequest(BaseModel):
    strategy: Optional[str] = Field(default=None, description="e.g. high_touch_voice")
    custom_message: Optional[str] = Field(default=None, description="agent-edited outbound copy")
    note: str = ""
    agent: str = "agent"


class ResolveRequest(BaseModel):
    note: str = ""
    agent: str = "agent"


class ConsentResponse(BaseModel):
    payment_id: str
    response: str = Field(pattern="^(yes|no)$")


@router.get("/queue")
async def get_triage_queue(db: Session = Depends(get_db)) -> dict:
    """Open tickets sorted by priority: high-value first, new customers second."""
    tickets = triage_service.list_open_tickets(db)
    return {"count": len(tickets), "tickets": [triage_service.ticket_to_dict(t) for t in tickets]}


@router.post("/{ticket_id}/override")
async def override_ticket(
    ticket_id: str,
    payload: OverrideRequest,
    db: Session = Depends(get_db),
) -> dict:
    ticket = db.get(TriageTicketRecord, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"triage ticket '{ticket_id}' not found")

    strategy: Optional[RecoveryStrategy] = None
    if payload.strategy:
        try:
            strategy = RecoveryStrategy(payload.strategy.strip().lower())
        except ValueError as exc:
            allowed = [s.value for s in RecoveryStrategy]
            raise HTTPException(
                status_code=422,
                detail=f"unknown strategy '{payload.strategy}'; expected one of {allowed}",
            ) from exc
    if strategy is None and not payload.custom_message:
        raise HTTPException(status_code=422, detail="provide a strategy override and/or custom_message")

    supervisor = get_supervisor()
    supervisor._bind_all(db)

    plan, _recovery = await supervisor.build_plan(
        db, ticket.payment_id, override_strategy=strategy, persist=True
    )

    if payload.custom_message:
        payment = supervisor._get_payment(db, ticket.payment_id)
        payment.meta = {**(payment.meta or {}), "custom_message": payload.custom_message}
        db.add(payment)

    ticket.overridden_strategy = strategy.value if strategy else None
    ticket.custom_message = payload.custom_message
    ticket.status = "resolved"
    ticket.resolution_note = payload.note or ("strategy overridden" if strategy else "message edited")
    ticket.resolved_by = payload.agent
    ticket.resolved_at = utcnow()
    db.add(ticket)
    db.flush()

    # Explicitly record the human escalation in the audit trail.
    supervisor.audit(
        AuditEventType.TRIAGE_OVERRIDE,
        resource_type="triage_ticket",
        resource_id=ticket.id,
        outcome="escalated_by_agent",
        severity=AuditSeverity.WARNING,
        message=payload.note,
        details={
            "payment_id": ticket.payment_id,
            "overridden_strategy": ticket.overridden_strategy,
            "custom_message_applied": bool(payload.custom_message),
            "new_plan_id": plan.plan_id,
            "agent": payload.agent,
        },
    )
    return {
        "ticket_id": ticket.id,
        "status": ticket.status,
        "payment_id": ticket.payment_id,
        "overridden_strategy": ticket.overridden_strategy,
        "custom_message_applied": bool(payload.custom_message),
        "new_plan_id": plan.plan_id,
    }


@router.post("/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: str,
    payload: ResolveRequest,
    db: Session = Depends(get_db),
) -> dict:
    ticket = db.get(TriageTicketRecord, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"triage ticket '{ticket_id}' not found")
    ticket.status = "resolved"
    ticket.resolution_note = payload.note or "closed by agent"
    ticket.resolved_by = payload.agent
    ticket.resolved_at = utcnow()
    db.add(ticket)
    db.flush()

    supervisor = get_supervisor()
    supervisor._bind_all(db)
    supervisor.audit(
        AuditEventType.TRIAGE_OVERRIDE,
        resource_type="triage_ticket",
        resource_id=ticket.id,
        outcome="resolved_by_agent",
        message=payload.note,
        details={"payment_id": ticket.payment_id, "agent": payload.agent},
    )
    return {"ticket_id": ticket.id, "status": ticket.status}


@public_router.post("/respond")
async def respond_to_consent(
    payload: ConsentResponse,
    db: Session = Depends(get_db),
) -> dict:
    """Customer answered the 'Would you like help?' outreach.

    YES  -> connect to the chatbot with recovery options.
    NO   -> log it and defer automated recovery for 72 hours.
    """
    consent_row = (
        db.query(ConsentRequestRecord)
        .filter(
            ConsentRequestRecord.payment_id == payload.payment_id,
            ConsentRequestRecord.status == "awaiting",
        )
        .order_by(ConsentRequestRecord.requested_at.desc())
        .first()
    )
    if consent_row is None:
        raise HTTPException(status_code=404, detail="no pending consent request for this payment")

    supervisor = get_supervisor()
    supervisor._bind_all(db)
    now = utcnow()

    if payload.response == "yes":
        consent_row.status = "accepted"
        consent_row.chatbot_session_id = f"chat_{uuid.uuid4().hex[:12]}"
        consent_row.responded_at = now
        db.add(consent_row)
        db.flush()
        supervisor.audit(
            AuditEventType.CUSTOMER_CONSENT_RESPONDED,
            resource_type="consent",
            resource_id=consent_row.id,
            outcome="accepted_chatbot_handoff",
            details={"payment_id": consent_row.payment_id, "session": consent_row.chatbot_session_id},
        )
        return {
            "status": "accepted",
            "payment_id": consent_row.payment_id,
            "chatbot_session": consent_row.chatbot_session_id,
            "options": [
                {"action": "retry_now", "label": "Retry payment now"},
                {"action": "switch_method", "label": "Try a different payment method"},
                {"action": "talk_to_human", "label": "Talk to a support agent"},
            ],
        }

    deferred_until = now + timedelta(hours=get_settings().consent_defer_hours)
    consent_row.status = "declined"
    consent_row.deferred_until = deferred_until
    consent_row.responded_at = now
    db.add(consent_row)
    db.flush()
    supervisor.audit(
        AuditEventType.CUSTOMER_CONSENT_RESPONDED,
        resource_type="consent",
        resource_id=consent_row.id,
        outcome=f"declined_deferred_{get_settings().consent_defer_hours}h",
        severity=AuditSeverity.WARNING,
        details={"payment_id": consent_row.payment_id, "deferred_until": deferred_until.isoformat()},
    )
    return {
        "status": "declined",
        "payment_id": consent_row.payment_id,
        "deferred_until": deferred_until.isoformat(),
    }
