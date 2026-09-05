"""Payments v1 router: failed-payment list, detail, journey, batch ingest, analyze, options."""

from __future__ import annotations

import csv
import io
import random
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.agents import get_supervisor
from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import PaymentRecord, RecoveryRecord
from app.database.session import get_db
from app.models.payment import PaymentStatus, utcnow
from app.models.recovery import RecoveryStatus
from app.routes.dashboard import _build_journey_nodes, _latest_recovery_for_payment, _status_label
from app.schemas.payment_schemas import PaymentIngestRequest, PaymentIngestResponse
from app.utils.formatters import paise_to_rupees

router = APIRouter(prefix="/payments", tags=["payments"], dependencies=[Depends(require_api_key)])


def _rupees(amount_paise: int) -> float:
    return round(amount_paise / 100.0, 2)


def _serialize_payment(payment: PaymentRecord, recovery: Optional[RecoveryRecord] = None) -> dict:
    return {
        "id": payment.id,
        "order_id": payment.order_id,
        "gateway_payment_id": payment.gateway_payment_id,
        "customer_name": payment.customer_name,
        "customer_email_masked": payment.customer_email_masked,
        "amount": _rupees(payment.amount_paise),
        "currency": payment.currency,
        "method": payment.method,
        "status": payment.status,
        "failure_reason": payment.failure_reason,
        "error_code": payment.error_code,
        "error_description": payment.error_description,
        "attempt_number": payment.attempt_number,
        "risk_score": payment.risk_score,
        "risk_band": payment.risk_band,
        "created_at": payment.created_at.isoformat(),
        "updated_at": payment.updated_at.isoformat(),
        "recovery_status": _status_label(recovery.status if recovery else RecoveryStatus.FAILED.value)
        if recovery
        else None,
        "recovered_amount": _rupees(recovery.recovered_amount_paise) if recovery else 0.0,
    }


@router.get("")
async def list_payments(
    request: Request,
    status: Optional[str] = Query(default=None, description="Payment status filter"),
    failure_reason: Optional[str] = Query(default=None),
    period_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    query = db.query(PaymentRecord)
    if status:
        query = query.filter(PaymentRecord.status == status)
    if failure_reason:
        query = query.filter(PaymentRecord.failure_reason == failure_reason)
    query = query.filter(PaymentRecord.created_at >= utcnow() - timedelta(days=period_days))

    total = query.count()
    payments = (
        query.order_by(PaymentRecord.created_at.desc()).offset(offset).limit(limit).all()
    )
    items = []
    for payment in payments:
        recovery = _latest_recovery_for_payment(db, payment.id)
        items.append(_serialize_payment(payment, recovery))

    data = {"total": total, "count": len(items), "offset": offset, "limit": limit, "payments": items}
    return success(data, agents=["SupervisorAgent"], latency_ms=elapsed_ms(started))


@router.get("/{payment_id}")
async def get_payment(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    recovery = _latest_recovery_for_payment(db, payment_id)
    recovery_journey = None
    if recovery:
        recovery_journey = {
            "recovery_id": recovery.id,
            "strategy": recovery.strategy,
            "status": recovery.status,
            "attempts": recovery.attempts,
            "max_attempts": recovery.max_attempts,
            "expected_amount": _rupees(recovery.expected_amount_paise),
            "recovered_amount": _rupees(recovery.recovered_amount_paise),
            "cost": _rupees(recovery.cost_paise),
            "created_at": recovery.created_at.isoformat(),
            "updated_at": recovery.updated_at.isoformat(),
        }
    data = {**_serialize_payment(payment, recovery), "recovery_journey": recovery_journey}
    return success(data, agents=["PaymentAnalyzer"], latency_ms=elapsed_ms(started))


@router.get("/{payment_id}/journey")
async def get_payment_journey(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    recovery = _latest_recovery_for_payment(db, payment_id)
    nodes = _build_journey_nodes(payment, recovery)
    data = {
        "payment_id": payment.id,
        "transaction_id": payment.order_id or payment.id,
        "amount": _rupees(payment.amount_paise),
        "status": _status_label(recovery.status if recovery else RecoveryStatus.FAILED.value),
        "recovered_amount": _rupees(recovery.recovered_amount_paise if recovery else 0),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    return success(data, agents=["ExecutorAgent", "StrategySelector"], latency_ms=elapsed_ms(started))


@router.post("/batch-ingest")
async def batch_ingest(
    request: Request,
    payments: Optional[List[PaymentIngestRequest]] = None,
    num_payments: Optional[int] = Query(default=None, ge=1, le=10_000),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    try:
        body = await request.json()
    except ValueError:
        body = {}
    records = body.get("payments") or body.get("items") or []
    csv_content = body.get("csv")
    if records and isinstance(records, list):
        payloads = [PaymentIngestRequest(**item) for item in records]
    elif csv_content:
        payloads = _parse_csv(csv_content)
    elif num_payments is not None:
        payloads = _synthetic_payloads(num_payments)
    else:
        return error("INVALID_BATCH", "Provide 'payments', 'items', or 'csv' in the request body", status_code=400, latency_ms=elapsed_ms(started), request=request)

    supervisor = get_supervisor()
    results = []
    for payload in payloads:
        payment, duplicate = await supervisor.ingest_payment(db, payload)
        results.append(
            PaymentIngestResponse(
                payment_id=payment.id,
                order_id=payment.order_id,
                status=payment.status,
                received_at=payment.created_at,
                duplicate=duplicate,
            ).model_dump(mode="json")
        )
    db.commit()
    data = {"ingested": len(results), "duplicates": sum(1 for r in results if r["duplicate"]), "results": results}
    return success(data, agents=["PaymentAnalyzer", "SupervisorAgent"], latency_ms=elapsed_ms(started))


def _synthetic_payloads(count: int) -> List[PaymentIngestRequest]:
    failure_reasons = [
        "insufficient_funds",
        "bank_decline",
        "card_expired",
        "authentication_timeout",
        "network_error",
    ]
    amounts = [500, 1000, 2000, 5000, 10000]
    return [
        PaymentIngestRequest(
            order_id=f"synthetic_order_{index:06d}",
            customer={
                "name": f"Synthetic Customer {index}",
                "email": f"synthetic-{index}@example.com",
                "phone": f"+9190000{index:05d}",
            },
            amount=random.choice(amounts),
            method="card",
            failure_reason_code=random.choice(failure_reasons),
            error_description="Synthetic payment failure",
            metadata={"source": "synthetic"},
        )
        for index in range(count)
    ]


def _parse_csv(content: str) -> List[PaymentIngestRequest]:
    reader = csv.DictReader(io.StringIO(content))
    payloads = []
    for row in reader:
        payloads.append(PaymentIngestRequest(**{k: v for k, v in row.items() if v}))
    return payloads


@router.post("/{payment_id}/analyze")
async def analyze_payment(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    try:
        payment, analysis = await get_supervisor().analyze_payment(db, payment_id)
    except Exception as exc:  # noqa: BLE001
        return error("ANALYZE_FAILED", str(exc), status_code=404, latency_ms=elapsed_ms(started), request=request)
    analysis_json = _normalize_analysis(analysis)
    data = {
        "payment_id": payment.id,
        "status": payment.status,
        "failure_reason": payment.failure_reason,
        "analysis": analysis_json,
    }
    return success(data, agents=["PaymentAnalyzer"], confidence=analysis_json.get("confidence"), latency_ms=elapsed_ms(started))


def _normalize_analysis(analysis) -> dict:
    if hasattr(analysis, "model_dump"):
        dumped = analysis.model_dump(mode="json")
        if hasattr(analysis, "confidence") and "confidence" not in dumped:
            dumped["confidence"] = analysis.confidence
        return dumped
    return analysis


@router.get("/{payment_id}/recovery-options")
async def recovery_options(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    try:
        _, analysis = await get_supervisor().analyze_payment(db, payment_id)
    except Exception:
        analyze_confidence, analysis = 0.7, None
    else:
        analyze_confidence = getattr(analysis, "confidence", 0.7)

    strategies = [
        {"strategy": "smart_retry", "channel": "gateway_retry", "confidence": round(min(analyze_confidence + 0.05, 1.0), 2), "estimated_cost_inr": 0.0, "rationale": "Cheapest path; immediate retry through the gateway."},
        {"strategy": "sms_link", "channel": "sms", "confidence": round(analyze_confidence + 0.02, 2), "estimated_cost_inr": 0.8, "rationale": "Personalized payment link invites a customer-initiated retry."},
        {"strategy": "voice_call", "channel": "voice_ivr", "confidence": round(max(analyze_confidence - 0.15, 0.1), 2), "estimated_cost_inr": 3.5, "rationale": "Higher-touch channel for high-value or high-risk payments."},
    ]
    data = {"payment_id": payment.id, "amount": _rupees(payment.amount_paise), "recommended": strategies}
    return success(data, agents=["StrategySelector", "ConsensusAgent"], confidence=strategies[0]["confidence"], latency_ms=elapsed_ms(started))
