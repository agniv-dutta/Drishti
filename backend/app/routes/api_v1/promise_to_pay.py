"""Promise-to-pay commitment tracking for failed payments."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import PaymentRecord, PromiseToPay, PromiseToPayTask
from app.database.session import get_db
from app.integrations.sms_provider import get_sms_provider
from app.models.payment import utcnow
from app.utils.formatters import format_inr

router = APIRouter(
    prefix="/recovery/promise-to-pay",
    tags=["promise-to-pay"],
    dependencies=[Depends(require_api_key)],
)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _payment_context(payment: PaymentRecord) -> tuple[str, str, str]:
    metadata = payment.meta or {}
    customer_id = str(metadata.get("customer_id") or payment.id)
    merchant_id = str(metadata.get("merchant_id") or "default")
    return customer_id, merchant_id, payment.customer_name


def _serialize_promise(promise: PromiseToPay) -> dict[str, Any]:
    return {
        "promise_id": promise.id,
        "payment_id": promise.payment_id,
        "customer_id": promise.customer_id,
        "customer": promise.customer_name,
        "amount": promise.promised_amount,
        "promised_date": promise.promised_date,
        "status": promise.status,
        "paid_date": promise.paid_date,
    }


@router.post("/record")
async def record_promise_to_pay(
    request: Request,
    payment_id: str = Query(...),
    promised_date: datetime = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    promised_date = _as_utc(promised_date)
    now = utcnow()
    if promised_date <= now:
        return error("INVALID_PROMISED_DATE", "promised_date must be in the future", status_code=422, latency_ms=elapsed_ms(started), request=request)

    try:
        customer = payment.to_domain().customer
    except Exception as exc:  # pragma: no cover - encryption configuration failure
        return error("CUSTOMER_CONTACT_UNAVAILABLE", str(exc), status_code=422, latency_ms=elapsed_ms(started), request=request)

    customer_id, merchant_id, customer_name = _payment_context(payment)
    promise = PromiseToPay(
        payment_id=payment.id,
        merchant_id=merchant_id,
        customer_id=customer_id,
        customer_name=customer_name,
        promised_amount=payment.amount_paise / 100,
        promised_date=promised_date,
        status="open",
    )
    db.add(promise)
    db.flush()
    reminder_time = promised_date - timedelta(hours=24)
    escalation_time = promised_date + timedelta(hours=1)
    db.add_all([
        PromiseToPayTask(
            promise_id=promise.id,
            payment_id=payment.id,
            task_type="promise_reminder",
            scheduled_for=reminder_time,
        ),
        PromiseToPayTask(
            promise_id=promise.id,
            payment_id=payment.id,
            task_type="promise_breach",
            scheduled_for=escalation_time,
        ),
    ])
    db.commit()

    sms_message = f"Thanks for committing to pay by {promised_date.strftime('%d %b')}. We'll remind you 24h before."
    sms_result = await get_sms_provider().send(customer.phone, sms_message)
    if not sms_result.success:
        return error("PROMISE_CONFIRMATION_FAILED", sms_result.detail or "Unable to send promise confirmation", status_code=502, latency_ms=elapsed_ms(started), request=request)

    return success({
        "status": "promise_recorded",
        "promise_id": promise.id,
        "payment_id": payment.id,
        "promised_date": promised_date,
        "reminder_scheduled_for": reminder_time,
        "escalation_scheduled_for": escalation_time,
        "sms_reference": sms_result.reference,
    }, agents=["PromiseToPayAgent"], latency_ms=elapsed_ms(started))


@router.get("/tracker")
async def get_promise_tracker(
    request: Request,
    merchant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    now = utcnow()
    promises = db.query(PromiseToPay).filter(PromiseToPay.merchant_id == merchant_id).all()
    tracking: dict[str, list[dict[str, Any]]] = {"fulfilled": [], "at_risk": [], "breached": []}

    for promise in promises:
        promised_date = _as_utc(promise.promised_date)
        if promise.status == "fulfilled":
            paid_date = _as_utc(promise.paid_date) if promise.paid_date else promised_date
            tracking["fulfilled"].append({
                "payment_id": promise.payment_id,
                "customer": promise.customer_name,
                "amount": promise.promised_amount,
                "promised_date": promise.promised_date,
                "actual_payment_date": promise.paid_date,
                "fulfillment": "ON_TIME" if paid_date <= promised_date else "LATE",
            })
        elif promise.status == "open" and promised_date > now:
            tracking["at_risk"].append({
                "payment_id": promise.payment_id,
                "customer": promise.customer_name,
                "amount": promise.promised_amount,
                "days_until_due": (promised_date - now).days,
                "status": "UPCOMING",
            })
        elif promise.status == "breached" or (promise.status == "open" and promised_date <= now):
            if promise.status == "open":
                promise.status = "breached"
            tracking["breached"].append({
                "payment_id": promise.payment_id,
                "customer": promise.customer_name,
                "amount": promise.promised_amount,
                "promised_date": promise.promised_date,
                "days_overdue": max(0, (now - promised_date).days),
                "action_needed": "ESCALATE",
            })

    db.commit()
    fulfilled_count = len(tracking["fulfilled"])
    fulfillment_rate = f"{fulfilled_count / len(promises) * 100:.1f}%" if promises else "0.0%"
    return success({
        "promise_summary": tracking,
        "fulfillment_rate": fulfillment_rate,
        "breached_amount": sum(item["amount"] for item in tracking["breached"]),
        "at_risk_amount": sum(item["amount"] for item in tracking["at_risk"]),
        "total_promises": len(promises),
    }, agents=["PromiseToPayAgent"], latency_ms=elapsed_ms(started))