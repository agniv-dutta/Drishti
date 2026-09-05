"""Dashboard aggregation endpoints used by the frontend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.database.models import PaymentRecord, RecoveryRecord
from app.models.payment import utcnow
from app.database.session import get_db
from app.models.chargeback import ChargebackRiskAssessment
from app.models.recovery import RecoveryStatus
from app.schemas.dashboard_schemas import (
    DashboardActivityItem,
    DashboardJourneyNode,
    DashboardJourneyResponse,
    DashboardOverviewResponse,
    DashboardPaymentItem,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_api_key)])


def _rupees(amount_paise: int) -> float:
    return round(amount_paise / 100.0, 2)


def _fmt_time(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _fmt_relative_time(value: datetime) -> str:
    now = datetime.now(timezone.utc)
    candidate = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    delta = now - candidate
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago"


def _status_label(status: str) -> str:
    if status == RecoveryStatus.SUCCEEDED.value:
        return "recovered"
    if status == RecoveryStatus.EXHAUSTED.value:
        return "escalated"
    return "failed"


def _activity_action(record: RecoveryRecord) -> tuple[str, str]:
    result = record.result_json or {}
    outcomes = [entry for entry in result.get("outcomes", []) if entry.get("status") != "skipped"]
    channel = (outcomes[0].get("channel") if outcomes else "") or record.strategy
    if channel == "sms":
        return "SMS sent", "Envelope"
    if channel == "email":
        return "Email opened", "Mail"
    if channel == "voice_ivr":
        return "Call completed", "Phone"
    if channel == "gateway_retry":
        return "Gateway retried", "RotateCcw"
    if channel == "crm_escalation":
        return "Escalated to CRM", "ShieldAlert"
    return "Workflow updated", "Sparkles"


def _select_primary_payment(db: Session, payment_id: Optional[str]) -> Optional[PaymentRecord]:
    if payment_id:
        return db.get(PaymentRecord, payment_id)

    preferred = (
        db.query(PaymentRecord)
        .join(RecoveryRecord, RecoveryRecord.payment_id == PaymentRecord.id)
        .order_by(desc(RecoveryRecord.updated_at))
        .first()
    )
    if preferred is not None:
        return preferred

    return db.query(PaymentRecord).order_by(PaymentRecord.created_at.desc()).first()


def _latest_recovery_for_payment(db: Session, payment_id: str) -> Optional[RecoveryRecord]:
    return (
        db.query(RecoveryRecord)
        .filter(RecoveryRecord.payment_id == payment_id)
        .order_by(RecoveryRecord.updated_at.desc())
        .first()
    )


def _build_payment_item(payment: PaymentRecord, recovery: Optional[RecoveryRecord]) -> DashboardPaymentItem:
    status = _status_label(recovery.status if recovery else RecoveryStatus.FAILED.value)
    strategy_used = recovery.strategy if recovery else "smart_retry"
    recovered_amount = _rupees(recovery.recovered_amount_paise if recovery else 0)
    last_updated = recovery.updated_at if recovery else payment.updated_at
    chargeback_risk = None
    if recovery and recovery.result_json and recovery.result_json.get("chargeback_risk"):
        chargeback_risk = ChargebackRiskAssessment(**recovery.result_json["chargeback_risk"])
    return DashboardPaymentItem(
        id=payment.id,
        amount=_rupees(payment.amount_paise),
        status=status,
        strategy_used=strategy_used,
        recovered_amount=recovered_amount,
        last_updated=last_updated,
        chargeback_risk=chargeback_risk,
    )


def _build_journey_nodes(payment: PaymentRecord, recovery: Optional[RecoveryRecord]) -> list[DashboardJourneyNode]:
    analysis = (recovery.analysis_json or {}) if recovery else {}
    result = (recovery.result_json or {}) if recovery else {}
    reasoning = analysis.get("reasoning") or []
    if isinstance(reasoning, list):
        reasoning_text = " ".join(str(item) for item in reasoning)
    else:
        reasoning_text = str(reasoning)

    recovered_amount = _rupees(recovery.recovered_amount_paise if recovery else 0)
    amount_label = f"{recovered_amount:,.0f}" if recovered_amount else None
    confidence = analysis.get("confidence")
    confidence_label = f"{round(float(confidence) * 100)}% confidence" if confidence is not None else None
    fail_reason = payment.failure_reason or "unknown"
    decline_reason = "Insufficient Funds" if fail_reason == "insufficient_funds" else fail_reason.replace("_", " ").title()

    sms_detail = "A personalized payment link was sent after the decline with a short retry prompt."
    outcomes = [entry for entry in result.get("outcomes", []) if entry.get("status") != "skipped"]
    sms_outcome = next((entry for entry in outcomes if entry.get("channel") == "sms"), None)
    if sms_outcome:
        sms_detail = sms_outcome.get("detail") or sms_detail

    nodes = [
        DashboardJourneyNode(
            id="created",
            title="Payment Initiated",
            subtitle="Payment Created",
            time=_fmt_time(payment.created_at),
            badge="Completed",
            badge_tone="sage",
            x=7,
            y="above",
            circle_tone="coral",
            current=False,
            completed=True,
            detail="The payment event was recorded by the backend and routed into the recovery pipeline.",
            status=payment.status,
        ),
        DashboardJourneyNode(
            id="declined",
            title="Declined by Bank",
            subtitle="Decline Detected",
            badge=decline_reason,
            badge_tone="gray",
            x=22,
            y="below",
            circle_tone="rose",
            current=False,
            completed=True,
            reason="Failure reason",
            detail=payment.error_description or f"Issuer returned {decline_reason.lower()} during authorization.",
        ),
        DashboardJourneyNode(
            id="analysis",
            title="AI Analyzed",
            subtitle="AI Analysis",
            badge=confidence_label,
            badge_tone="coral",
            x=40,
            y="above",
            circle_tone="coral",
            current=False,
            completed=True,
            detail="The model selected the recovery channel from the failure context and customer history.",
            reasoning=reasoning_text or "The backend selected the recovery strategy using the recovery classifier and heuristics.",
        ),
        DashboardJourneyNode(
            id="sms",
            title="Customer Contacted",
            subtitle="SMS Sent",
            time=_fmt_time(recovery.updated_at if recovery else payment.updated_at),
            x=58,
            y="below",
            circle_tone="coral",
            current=False,
            completed=True,
            preview="Hi, payment failed. Retry now: [link]",
            detail=sms_detail,
        ),
        DashboardJourneyNode(
            id="retried",
            title="Retry Successful",
            subtitle="Payment Retried",
            amount=amount_label or "0",
            x=76,
            y="above",
            circle_tone="coral",
            current=False,
            completed=True,
            detail="The customer retried the payment from the recovery link and the transaction cleared successfully.",
        ),
        DashboardJourneyNode(
            id="complete",
            title="Revenue Recovered",
            subtitle="Recovery Complete",
            amount=amount_label or "0",
            x=92,
            y="below",
            circle_tone="gold",
            current=bool(recovery and recovery.status == RecoveryStatus.SUCCEEDED.value),
            completed=True,
            detail="Recovery closed with a fully successful payment and an auditable backend trail.",
        ),
    ]

    if recovery and recovery.status != RecoveryStatus.SUCCEEDED.value:
        nodes[5].title = "Recovery In Progress"
        nodes[5].subtitle = "Current Step"
        nodes[5].current = True
        nodes[5].amount = None
        nodes[4].current = True
        nodes[4].detail = "The retry step completed, but the final recovery has not been confirmed yet."

    return nodes


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_overview(
    payment_id: Optional[str] = Query(default=None),
    limit: int = Query(default=5, ge=1, le=50),
    period_days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> DashboardOverviewResponse:
    cutoff = utcnow() - timedelta(days=period_days)
    records = (
        db.query(RecoveryRecord, PaymentRecord)
        .join(PaymentRecord, PaymentRecord.id == RecoveryRecord.payment_id)
        .filter(RecoveryRecord.created_at >= cutoff)
        .order_by(RecoveryRecord.updated_at.desc())
        .limit(limit)
        .all()
    )
    active_recoveries = [
        _build_payment_item(payment, recovery)
        for recovery, payment in records
    ]

    total_payments_processed = (
        db.query(func.count(PaymentRecord.id))
        .filter(PaymentRecord.created_at >= cutoff)
        .scalar() or 0
    )
    total_recovered_paise = sum(
        recovery.recovered_amount_paise
        for recovery, _ in records
        if recovery.status == RecoveryStatus.SUCCEEDED.value
    )
    successful = sum(1 for recovery, _ in records if recovery.status == RecoveryStatus.SUCCEEDED.value)
    recovery_rate = round(successful / len(records) * 100, 2) if records else 0.0

    activity_feed: list[DashboardActivityItem] = []
    for recovery, payment in records[:5]:
        action, icon = _activity_action(recovery)
        activity_feed.append(
            DashboardActivityItem(
                label=f"Payment #{payment.id[-4:].upper()}",
                action=action,
                amount=f"{_rupees(recovery.recovered_amount_paise):,.0f} recovered",
                time=_fmt_relative_time(recovery.updated_at),
                icon=icon,
                payment_id=payment.id,
            )
        )

    primary_payment = _select_primary_payment(db, payment_id)
    selected_payment_id = primary_payment.id if primary_payment else (active_recoveries[0].id if active_recoveries else None)

    return DashboardOverviewResponse(
        selected_payment_id=selected_payment_id,
        recovery_rate=recovery_rate,
        target_rate=60.0,
        total_recovered=_rupees(total_recovered_paise),
        total_payments_processed=total_payments_processed,
        active_recoveries=active_recoveries,
        activity_feed=activity_feed,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/journey/{payment_id}", response_model=DashboardJourneyResponse)
async def get_journey(
    payment_id: str,
    db: Session = Depends(get_db),
) -> DashboardJourneyResponse:
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail=f"payment '{payment_id}' not found")

    recovery = _latest_recovery_for_payment(db, payment_id)
    recovered_amount = _rupees(recovery.recovered_amount_paise if recovery else 0)
    subtitle = f"Transaction ID: #{payment.order_id or payment.id[:8].upper()}"

    return DashboardJourneyResponse(
        payment_id=payment.id,
        transaction_id=payment.order_id or payment.id,
        title="Recovery Journey",
        subtitle=subtitle,
        amount=_rupees(payment.amount_paise),
        status=_status_label(recovery.status if recovery else RecoveryStatus.FAILED.value),
        recovered_amount=recovered_amount,
        nodes=_build_journey_nodes(payment, recovery),
        chargeback_risk=(
            ChargebackRiskAssessment(**(recovery.result_json.get("chargeback_risk") or {}))
            if recovery and recovery.result_json and recovery.result_json.get("chargeback_risk")
            else None
        ),
        generated_at=datetime.now(timezone.utc),
    )
