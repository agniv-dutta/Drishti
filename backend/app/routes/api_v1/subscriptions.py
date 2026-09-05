"""Failed subscription payment recovery endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import SubscriptionPayment, SubscriptionRecoveryEvent
from app.database.session import get_db
from app.integrations.email_provider import EmailContent, get_email_provider
from app.models.payment import utcnow

router = APIRouter(
    prefix="/recovery/subscription",
    tags=["subscription-recovery"],
    dependencies=[Depends(require_api_key)],
)


class SubscriptionPaymentCreate(BaseModel):
    merchant_id: str
    customer_id: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    subscription_id: str
    subscription_name: str = "subscription"
    billing_cycle: int = Field(default=1, ge=1)
    amount: float = Field(gt=0)
    failure_reason: str = "declined_by_issuer"
    retry_count: int = Field(default=0, ge=0)
    retry_schedule: list[str] = ["T+3h", "T+24h", "T+72h"]
    status: Literal["failed", "retrying", "recovered", "suspended"] = "failed"
    support_complaints: int = Field(default=0, ge=0)
    months_active: float = Field(default=1, ge=0)
    lifetime_value: float = Field(default=0, ge=0)
    last_login: Optional[datetime] = None


def _churn_score(payment: SubscriptionPayment, failure_count: int = 0) -> float:
    failure_signal = min(failure_count / 3, 1.0) * 0.35
    complaint_signal = min(payment.support_complaints / 2, 1.0) * 0.25
    tenure_signal = 0.20 if payment.months_active < 3 else -0.10 if payment.months_active >= 12 else 0.0
    login_signal = 0.20 if payment.last_login and (utcnow() - _as_utc(payment.last_login)).days > 30 else 0.0
    return round(min(0.99, max(0.01, 0.30 + failure_signal + complaint_signal + tenure_signal + login_signal)), 3)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _serialize(payment: SubscriptionPayment, events: Optional[list[SubscriptionRecoveryEvent]] = None) -> dict[str, Any]:
    return {
        "id": payment.id,
        "merchant_id": payment.merchant_id,
        "customer_id": payment.customer_id,
        "customer_name": payment.customer_name,
        "customer_email": payment.customer_email,
        "subscription_id": payment.subscription_id,
        "subscription_name": payment.subscription_name,
        "billing_cycle": payment.billing_cycle,
        "amount": payment.amount,
        "failure_reason": payment.failure_reason,
        "retry_count": payment.retry_count,
        "retry_schedule": payment.retry_schedule,
        "status": payment.status,
        "churn_risk": payment.churn_risk,
        "last_action": payment.last_action,
        "next_retry_at": payment.next_retry_at,
        "events": [
            {"id": event.id, "action": event.action, "status": event.status, "message": event.message, "scheduled_for": event.scheduled_for, "created_at": event.created_at}
            for event in (events or [])
        ],
    }


@router.post("/payments")
async def create_subscription_payment(payload: SubscriptionPaymentCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    started = measure()
    payment = SubscriptionPayment(**payload.model_dump())
    payment.churn_risk = _churn_score(payment, 1 if payment.status == "failed" else 0)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return success(_serialize(payment), agents=["SubscriptionRecoveryAgent"], latency_ms=elapsed_ms(started))


@router.get("/payments")
async def list_subscription_payments(
    request: Request,
    merchant_id: str = Query(...),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    query = db.query(SubscriptionPayment).filter(SubscriptionPayment.merchant_id == merchant_id)
    if status:
        query = query.filter(SubscriptionPayment.status == status)
    payments = query.order_by(SubscriptionPayment.updated_at.desc()).all()
    failure_counts = {}
    for payment in payments:
        failure_counts[payment.customer_id] = failure_counts.get(payment.customer_id, 0) + 1
    for payment in payments:
        payment.churn_risk = _churn_score(payment, failure_counts[payment.customer_id])
    db.commit()
    return success({"payments": [_serialize(payment) for payment in payments], "count": len(payments)}, agents=["SubscriptionRecoveryAgent"], latency_ms=elapsed_ms(started))


@router.post("/handle-failure")
async def handle_subscription_failure(
    request: Request,
    subscription_payment_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(SubscriptionPayment, subscription_payment_id)
    if payment is None:
        return error("SUBSCRIPTION_PAYMENT_NOT_FOUND", f"subscription payment '{subscription_payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    now = utcnow()
    if payment.retry_count == 0:
        strategy, confidence = "immediate_retry", 0.92
        message = "Soft decline detected. Retrying payment immediately."
        next_retry = now
        status = "retrying"
    elif payment.retry_count == 1:
        strategy, confidence = "delayed_retry", 0.85
        message = "First retry failed. Waiting 24h for card refresh."
        next_retry = now + timedelta(hours=24)
        status = "retrying"
    elif payment.retry_count == 2:
        strategy, confidence = "card_update_prompt", 0.78
        message = f"Hi {payment.customer_name}, your {payment.subscription_name} renewal failed. Please update your card to keep your subscription active: [link]"
        next_retry = now + timedelta(hours=24)
        status = "retrying"
        email = await get_email_provider().send(
            payment.customer_email,
            EmailContent(
                subject=f"Update your card to keep {payment.subscription_name} active",
                plain=message,
                html=message.replace("\n", "<br>"),
            ),
        )
        if not email.success:
            return error("CARD_UPDATE_PROMPT_FAILED", email.detail or "Unable to send card update prompt", status_code=502, latency_ms=elapsed_ms(started), request=request)
    else:
        strategy, confidence = "suspend_warning", 0.65
        message = f"Your subscription will be suspended in 7 days if payment is not received. Please update your card to avoid interruption."
        next_retry = None
        status = "suspended"
        email = await get_email_provider().send(
            payment.customer_email,
            EmailContent(subject=f"Action required: {payment.subscription_name} payment", plain=message, html=message),
        )
        if not email.success:
            return error("SUSPENSION_WARNING_FAILED", email.detail or "Unable to send suspension warning", status_code=502, latency_ms=elapsed_ms(started), request=request)

    payment.status = status
    payment.retry_count += 1
    payment.last_action = strategy
    payment.next_retry_at = next_retry
    payment.churn_risk = _churn_score(payment, payment.retry_count + 1)
    event = SubscriptionRecoveryEvent(
        subscription_payment_id=payment.id,
        action=strategy,
        status=status,
        message=message,
        scheduled_for=next_retry,
    )
    db.add(event)
    db.commit()
    return success({"subscription_payment_id": payment.id, "strategy": strategy, "confidence": confidence, "message": message, "next_retry": next_retry, "days_until_suspension": 7 if strategy == "suspend_warning" else None}, agents=["SubscriptionRecoveryAgent"], confidence=confidence, latency_ms=elapsed_ms(started))


@router.get("/churn-risk")
async def get_churn_risk(customer_id: str = Query(...), request: Request = None, db: Session = Depends(get_db)) -> dict:
    started = measure()
    subscriptions = db.query(SubscriptionPayment).filter(SubscriptionPayment.customer_id == customer_id).all()
    if not subscriptions:
        return error("CUSTOMER_NOT_FOUND", f"customer '{customer_id}' has no subscription payments", status_code=404, latency_ms=elapsed_ms(started), request=request)
    failures = sum(1 for item in subscriptions if item.status in {"failed", "retrying", "suspended"})
    latest = max(subscriptions, key=lambda item: item.updated_at)
    risk = _churn_score(latest, failures)
    recommendation = "AGGRESSIVE_RECOVERY - High risk of losing customer" if risk > 0.7 else "STANDARD_RECOVERY" if risk > 0.4 else "GENTLE_RECOVERY - Low churn risk, customer loyal"
    return success({"customer_id": customer_id, "churn_risk": risk, "recommendation": recommendation, "ltv_at_risk": round(latest.amount * 12 * max(latest.months_active / 12, 1), 2), "signals": {"payment_failures": failures, "support_complaints": latest.support_complaints, "months_active": latest.months_active, "ltv": latest.lifetime_value}}, agents=["SubscriptionRiskAgent"], confidence=0.75, latency_ms=elapsed_ms(started))
