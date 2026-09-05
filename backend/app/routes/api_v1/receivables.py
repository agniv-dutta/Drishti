"""B2B receivables recovery endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import BillingInvoice, BillingPaymentPromise, BillingReminderLog
from app.database.session import get_db
from app.integrations.email_provider import EmailContent, get_email_provider
from app.models.payment import utcnow

router = APIRouter(
    prefix="/recovery/b2b",
    tags=["b2b-receivables"],
    dependencies=[Depends(require_api_key)],
)


class BillingInvoiceCreate(BaseModel):
    merchant_id: str
    customer_id: str
    customer_name: str
    customer_contact_name: str = "Accounts Payable"
    customer_email: str
    invoice_number: str
    amount: float = Field(gt=0)
    issue_date: datetime
    due_date: datetime
    payment_terms: str = "Net 30"
    status: Literal["draft", "sent", "overdue", "disputed", "partially_paid", "paid"] = "sent"


class PaymentPromiseCreate(BaseModel):
    promised_date: datetime
    promised_amount: float = Field(gt=0)


def _invoice_payload(invoice: BillingInvoice, db: Session) -> dict[str, Any]:
    invoice.refresh_days_overdue()
    reminders = (
        db.query(BillingReminderLog)
        .filter(BillingReminderLog.invoice_id == invoice.id)
        .order_by(BillingReminderLog.sent_at.desc())
        .all()
    )
    promises = (
        db.query(BillingPaymentPromise)
        .filter(BillingPaymentPromise.invoice_id == invoice.id)
        .order_by(BillingPaymentPromise.created_at.desc())
        .all()
    )
    risk = _score_payment_risk(invoice)
    return {
        "id": invoice.id,
        "merchant_id": invoice.merchant_id,
        "customer_id": invoice.customer_id,
        "customer_name": invoice.customer_name,
        "contact_name": invoice.customer_contact_name,
        "customer_email": invoice.customer_email,
        "invoice_number": invoice.invoice_number,
        "amount": invoice.amount,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "days_overdue": invoice.days_overdue,
        "payment_terms": invoice.payment_terms,
        "status": invoice.status,
        "last_reminder": invoice.last_reminder,
        "reminder_count": invoice.reminder_count,
        "risk_score": risk,
        "recommended_action": "send_reminder" if invoice.days_overdue < 30 else "escalate",
        "reminders": [
            {"id": item.id, "sent_at": item.sent_at, "template": item.template, "status": item.status, "provider_reference": item.provider_reference}
            for item in reminders
        ],
        "payment_promises": [
            {"id": item.id, "promised_date": item.promised_date, "promised_amount": item.promised_amount, "status": item.status, "created_at": item.created_at}
            for item in promises
        ],
    }


def _score_payment_risk(invoice: BillingInvoice) -> float:
    """Transparent heuristic until invoice-level training data is available."""
    days_factor = min(max(invoice.days_overdue, 0) / 60, 1.0) * 0.55
    reminder_factor = min(invoice.reminder_count, 3) / 3 * 0.20
    amount_factor = min(invoice.amount / 1_000_000, 1.0) * 0.10
    dispute_factor = 0.25 if invoice.status == "disputed" else 0.0
    return round(min(0.99, 0.10 + days_factor + reminder_factor + amount_factor + dispute_factor), 3)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.post("/invoices")
async def create_invoice(payload: BillingInvoiceCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    started = measure()
    invoice = BillingInvoice(**payload.model_dump())
    invoice.refresh_days_overdue()
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return success(_invoice_payload(invoice, db), agents=["ReceivablesSupervisor"], latency_ms=elapsed_ms(started))


@router.get("/invoices")
async def list_invoices(
    request: Request,
    merchant_id: str = Query(...),
    status: Optional[str] = Query(default=None),
    sort_by: Literal["amount", "days_overdue", "due_date"] = Query(default="days_overdue"),
    descending: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    query = db.query(BillingInvoice).filter(BillingInvoice.merchant_id == merchant_id)
    if status:
        query = query.filter(BillingInvoice.status == status)
    invoices = query.all()
    for invoice in invoices:
        invoice.refresh_days_overdue()
    sort_key = {
        "amount": lambda item: item.amount,
        "days_overdue": lambda item: item.days_overdue,
        "due_date": lambda item: item.due_date,
    }[sort_by]
    invoices.sort(key=sort_key, reverse=descending)
    db.commit()
    data = {"invoices": [_invoice_payload(item, db) for item in invoices], "count": len(invoices), "sort_by": sort_by, "descending": descending}
    return success(data, agents=["ReceivablesSupervisor"], latency_ms=elapsed_ms(started))


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    started = measure()
    invoice = db.get(BillingInvoice, invoice_id)
    if invoice is None:
        return error("INVOICE_NOT_FOUND", f"invoice '{invoice_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    return success(_invoice_payload(invoice, db), agents=["ReceivablesSupervisor"], latency_ms=elapsed_ms(started))


@router.post("/detect-overdue")
async def detect_overdue_receivables(merchant_id: str = Query(...), request: Request = None, db: Session = Depends(get_db)) -> dict:
    started = measure()
    invoices = db.query(BillingInvoice).filter(BillingInvoice.merchant_id == merchant_id, BillingInvoice.status == "overdue").all()
    at_risk = []
    for invoice in invoices:
        invoice.refresh_days_overdue()
        risk_score = _score_payment_risk(invoice)
        if risk_score > 0.6:
            at_risk.append({
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "customer_name": invoice.customer_name,
                "amount": invoice.amount,
                "days_overdue": invoice.days_overdue,
                "risk_score": risk_score,
                "recommended_action": "send_reminder" if invoice.days_overdue < 30 else "escalate",
            })
    db.commit()
    return success({"overdue_invoices": at_risk}, agents=["ReceivablesRiskAgent"], latency_ms=elapsed_ms(started))


@router.post("/send-reminder")
async def send_b2b_reminder(invoice_id: str = Query(...), request: Request = None, db: Session = Depends(get_db)) -> dict:
    started = measure()
    invoice = db.get(BillingInvoice, invoice_id)
    if invoice is None:
        return error("INVOICE_NOT_FOUND", f"invoice '{invoice_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    invoice.refresh_days_overdue()
    sequence = [
        ("soft_reminder", "Friendly reminder: your invoice is due. Please arrange payment at your earliest convenience."),
        ("firm_reminder", "This invoice is now overdue. Please remit payment immediately to avoid late fees."),
        ("escalation", "Your account is significantly overdue. We require immediate payment and may escalate this matter."),
    ]
    template, body = sequence[min(invoice.reminder_count, len(sequence) - 1)]
    message = (
        f"Hi {invoice.customer_contact_name},\n\n{body}\n\n"
        f"Invoice #{invoice.invoice_number}: ₹{invoice.amount:,.2f}\n"
        f"Due date: {invoice.due_date.strftime('%d %b %Y')}\n\nThank you."
    )
    result = await get_email_provider().send(
        invoice.customer_email,
        EmailContent(
            subject=f"Payment Reminder: Invoice #{invoice.invoice_number}",
            plain=message,
            html=message.replace("\n", "<br>"),
        ),
    )
    if not result.success:
        return error("REMINDER_FAILED", result.detail or "Unable to send reminder", status_code=502, latency_ms=elapsed_ms(started), request=request)

    sent_at = utcnow()
    db.add(BillingReminderLog(invoice_id=invoice.id, sent_at=sent_at, template=template, status="sent", provider_reference=result.reference))
    invoice.last_reminder = sent_at
    invoice.reminder_count += 1
    db.commit()
    return success({"status": "reminder_sent", "template": template, "provider_reference": result.reference, "next_reminder": sent_at + timedelta(days=15)}, agents=["ReceivablesRecoveryAgent"], latency_ms=elapsed_ms(started))


@router.post("/invoices/{invoice_id}/promise")
async def record_payment_promise(invoice_id: str, payload: PaymentPromiseCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    started = measure()
    invoice = db.get(BillingInvoice, invoice_id)
    if invoice is None:
        return error("INVOICE_NOT_FOUND", f"invoice '{invoice_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    promise = BillingPaymentPromise(invoice_id=invoice.id, promised_date=payload.promised_date, promised_amount=payload.promised_amount)
    invoice.promise_date = payload.promised_date
    invoice.promise_amount = payload.promised_amount
    db.add(promise)
    db.commit()
    return success({"promise_id": promise.id, "invoice_id": invoice.id, "status": promise.status, "promised_date": promise.promised_date, "promised_amount": promise.promised_amount}, agents=["ReceivablesRecoveryAgent"], latency_ms=elapsed_ms(started))


@router.get("/dso-tracker")
async def get_dso_metrics(merchant_id: str = Query(...), request: Request = None, db: Session = Depends(get_db)) -> dict:
    started = measure()
    invoices = db.query(BillingInvoice).filter(BillingInvoice.merchant_id == merchant_id).all()
    for invoice in invoices:
        invoice.refresh_days_overdue()
    total_ar = sum(item.amount for item in invoices if item.status not in {"paid", "disputed"})
    period_start = utcnow() - timedelta(days=30)
    total_sales = sum(item.amount for item in invoices if _as_utc(item.issue_date) >= period_start)
    dso = round((total_ar / total_sales) * 30, 1) if total_sales else 0.0
    overdue = [item for item in invoices if item.days_overdue > 0 and item.status not in {"paid", "disputed"}]
    data = {
        "dso": dso,
        "benchmark": 45.0,
        "improvement": f"DSO {'above' if dso > 45 else 'below'} benchmark by {abs(dso - 45):.1f} days",
        "overdue_invoices": len(overdue),
        "total_overdue_amount": round(sum(item.amount for item in overdue), 2),
        "total_accounts_receivable": round(total_ar, 2),
        "total_sales_period": round(total_sales, 2),
        "timestamp": utcnow(),
    }
    return success(data, agents=["ReceivablesAnalyticsAgent"], latency_ms=elapsed_ms(started))
