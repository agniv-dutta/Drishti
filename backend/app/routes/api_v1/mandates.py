"""Mandate recurring-debit recovery endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import Mandate, MandateRetry
from app.database.session import get_db
from app.models.payment import utcnow

router = APIRouter(
    prefix="/recovery/mandate",
    tags=["mandate-recovery"],
    dependencies=[Depends(require_api_key)],
)

RETRY_SCHEDULE = {
    0: {"delay": "0h", "strategy": "immediate_retry"},
    1: {"delay": "5d", "strategy": "retry_after_5_days"},
    2: {"delay": "10d", "strategy": "retry_after_10_days"},
}


class MandateCreate(BaseModel):
    merchant_id: str
    customer_name: str
    amount: float = Field(gt=0)
    retry_attempts: int = Field(default=0, ge=0)
    status: str = "active"
    failure_date: Optional[datetime] = None
    promised_date: Optional[datetime] = None


def _serialize_mandate(mandate: Mandate) -> dict:
    return {
        "mandate_id": mandate.id,
        "merchant_id": mandate.merchant_id,
        "customer_name": mandate.customer_name,
        "amount": mandate.amount,
        "retry_attempts": mandate.retry_attempts,
        "status": mandate.status,
        "failure_date": mandate.failure_date,
        "promised_date": mandate.promised_date,
    }


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.post("/mandates")
async def create_mandate(payload: MandateCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    started = measure()
    mandate = Mandate(**payload.model_dump())
    db.add(mandate)
    db.commit()
    db.refresh(mandate)
    return success(_serialize_mandate(mandate), agents=["MandateRecoveryAgent"], latency_ms=elapsed_ms(started))


@router.post("/handle-failure")
async def handle_mandate_failure(
    request: Request,
    mandate_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    mandate = db.get(Mandate, mandate_id)
    if mandate is None:
        return error("MANDATE_NOT_FOUND", f"mandate '{mandate_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    current_attempt = mandate.retry_attempts
    next_action = RETRY_SCHEDULE.get(
        current_attempt,
        {"delay": "escalate", "strategy": "escalate_to_human"},
    )
    now = utcnow()
    next_retry_time = None
    if next_action["delay"] != "escalate":
        if next_action["delay"].endswith("h"):
            delay = timedelta(hours=int(next_action["delay"][:-1]))
        else:
            delay = timedelta(days=int(next_action["delay"][:-1]))
        next_retry_time = now + delay
        db.add(MandateRetry(
            mandate_id=mandate.id,
            scheduled_for=next_retry_time,
            attempt_number=current_attempt + 1,
            reason="Mandate retry per sequencer",
        ))
        mandate.retry_attempts = current_attempt + 1
        mandate.status = "retrying"
        mandate.failure_date = mandate.failure_date or now
    else:
        mandate.status = "escalated"

    db.commit()
    return success({
        "mandate_id": mandate.id,
        "current_attempt": current_attempt,
        "next_retry": {**next_action, "scheduled_for": next_retry_time},
        "total_retries_allowed": 3,
        "status": "scheduled" if next_retry_time else "escalated",
    }, agents=["MandateRecoveryAgent"], latency_ms=elapsed_ms(started))


@router.get("/deferral-tracker")
async def track_mandate_deferrals(
    request: Request,
    merchant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    now = utcnow()
    deferred = db.query(Mandate).filter(
        Mandate.merchant_id == merchant_id,
        Mandate.status == "deferred",
    ).all()
    tracking = []
    for mandate in deferred:
        failure_date = _as_utc(mandate.failure_date or mandate.created_at)
        commitment_status = "UNFULFILLED"
        if mandate.promised_date and _as_utc(mandate.promised_date) < now:
            commitment_status = "OVERDUE"
        tracking.append({
            "mandate_id": mandate.id,
            "customer_name": mandate.customer_name,
            "amount": mandate.amount,
            "promised_date": mandate.promised_date,
            "days_deferred": max(0, (now - failure_date).days),
            "commitment_status": commitment_status,
        })
    return success({"deferred_mandates": tracking}, agents=["MandateRecoveryAgent"], latency_ms=elapsed_ms(started))