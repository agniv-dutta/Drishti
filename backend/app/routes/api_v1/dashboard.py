"""Dashboard v1 router: overview, agent progress, live metrics stream, exports."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import AuditRecord, PaymentRecord, RecoveryRecord
from app.database.session import get_db
from app.metrics.collector import MetricsCollector
from app.models.payment import utcnow
from app.models.recovery import RecoveryStatus
from app.routes.dashboard import (
    _build_journey_nodes,
    _build_payment_item,
    _latest_recovery_for_payment,
    _select_primary_payment,
    _status_label,
)
from app.schemas.dashboard_schemas import DashboardJourneyResponse, DashboardOverviewResponse
from app.utils.formatters import paise_to_rupees

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

collector = MetricsCollector()


def _rupees(amount_paise: int) -> float:
    return round(amount_paise / 100.0, 2)


@router.get("/overview", dependencies=[Depends(require_api_key)])
async def get_overview(
    request: Request,
    payment_id: Optional[str] = Query(default=None),
    limit: int = Query(default=5, ge=1, le=50),
    period_days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    cutoff = utcnow() - timedelta(days=period_days)
    records = (
        db.query(RecoveryRecord, PaymentRecord)
        .join(PaymentRecord, PaymentRecord.id == RecoveryRecord.payment_id)
        .filter(RecoveryRecord.created_at >= cutoff)
        .order_by(RecoveryRecord.updated_at.desc())
        .limit(limit)
        .all()
    )
    active_recoveries = [_build_payment_item(payment, recovery) for recovery, payment in records]

    total_payments_processed = (
        db.query(func.count(PaymentRecord.id)).filter(PaymentRecord.created_at >= cutoff).scalar() or 0
    )
    total_recovered_paise = sum(
        recovery.recovered_amount_paise
        for recovery, _ in records
        if recovery.status == RecoveryStatus.SUCCEEDED.value
    )
    successful = sum(
        1 for recovery, _ in records if recovery.status == RecoveryStatus.SUCCEEDED.value
    )
    recovery_rate = round(successful / len(records) * 100, 2) if records else 0.0

    activity_feed = []
    for recovery, payment in records[:5]:
        action, _icon = ("Recovered", "")
        activity_feed.append(
            {
                "label": f"Payment #{payment.id[-4:].upper()}",
                "action": action,
                "amount": f"{_rupees(recovery.recovered_amount_paise):,.0f} recovered",
                "time": _relative(recovery.updated_at),
                "icon": "Sparkles",
                "payment_id": payment.id,
            }
        )

    primary = _select_primary_payment(db, payment_id)
    selected_payment_id = primary.id if primary else (active_recoveries[0].id if active_recoveries else None)

    data = DashboardOverviewResponse(
        selected_payment_id=selected_payment_id,
        recovery_rate=recovery_rate,
        target_rate=60.0,
        total_recovered=_rupees(total_recovered_paise),
        total_payments_processed=total_payments_processed,
        active_recoveries=active_recoveries,
        activity_feed=activity_feed,
        generated_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")
    return success(data, agents=["SupervisorAgent"], latency_ms=elapsed_ms(started))


def _relative(value: datetime) -> str:
    now = datetime.now(timezone.utc)
    candidate = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    delta = now - candidate
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    return f"{minutes // 60}h ago"


@router.get("/journey/{payment_id}", dependencies=[Depends(require_api_key)])
async def get_journey(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    recovery = _latest_recovery_for_payment(db, payment_id)
    recovered_amount = _rupees(recovery.recovered_amount_paise if recovery else 0)
    subtitle = f"Transaction ID: #{payment.order_id or payment.id[:8].upper()}"
    chargeback_risk = None
    if recovery and recovery.result_json and recovery.result_json.get("chargeback_risk"):
        from app.models.chargeback import ChargebackRiskAssessment

        chargeback_risk = ChargebackRiskAssessment(**recovery.result_json["chargeback_risk"])
    data = DashboardJourneyResponse(
        payment_id=payment.id,
        transaction_id=payment.order_id or payment.id,
        title="Recovery Journey",
        subtitle=subtitle,
        amount=_rupees(payment.amount_paise),
        status=_status_label(recovery.status if recovery else RecoveryStatus.FAILED.value),
        recovered_amount=recovered_amount,
        nodes=_build_journey_nodes(payment, recovery),
        chargeback_risk=chargeback_risk,
        generated_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")
    return success(data, agents=["ExecutorAgent"], latency_ms=elapsed_ms(started))


@router.get("/metrics-summary", dependencies=[Depends(require_api_key)])
async def get_metrics_summary(
    request: Request,
    period: str = Query(default="current"),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    days = 30 if period == "monthly" else 7
    cutoff = utcnow() - timedelta(days=days)
    payments = db.query(PaymentRecord).filter(PaymentRecord.created_at >= cutoff).all()
    recoveries = db.query(RecoveryRecord).filter(RecoveryRecord.created_at >= cutoff).all()
    recovered = [item for item in recoveries if item.status == RecoveryStatus.SUCCEEDED.value]
    recovered_count = len(recovered)
    total_recovered = sum(item.recovered_amount_paise for item in recovered)

    def strategy_total(strategy: str) -> float:
        return round(sum(item.recovered_amount_paise for item in recovered if item.strategy == strategy) / 100, 2)

    data = {
        "period": period,
        "total_payments": len(payments),
        "total_payments_change": 0,
        "recovery_rate": round(recovered_count / len(payments) * 100, 1) if payments else 0.0,
        "recovery_target": 60.0,
        "total_recovered": round(total_recovered / 100, 2),
        "weekly_change": 0.0,
        "avg_cost_per_recovery": round(sum(item.cost_paise for item in recovered) / recovered_count / 100, 2) if recovered_count else 0.0,
        "retry_recovered": strategy_total("smart_retry"),
        "sms_recovered": strategy_total("nudge_digital"),
        "call_recovered": strategy_total("high_touch_voice"),
        "timestamp": utcnow(),
    }
    return success(data, agents=["AuditSupervisor"], latency_ms=elapsed_ms(started))


@router.get("/agents-status", dependencies=[Depends(require_api_key)])
async def get_agents_status(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    total_recoveries = db.query(func.count(RecoveryRecord.id)).scalar() or 0
    recovered = (
        db.query(func.count(RecoveryRecord.id))
        .filter(RecoveryRecord.status == RecoveryStatus.SUCCEEDED.value, RecoveryRecord.attempts > 0)
        .scalar() or 0
    )

    agents = [
        {"name": "PaymentAnalyzer", "label": "Failure cause detection", "progress": 100, "status": "idle", "queue": _queue_depth(db, "analysis")},
        {"name": "StrategySelector", "label": "Recovery strategy selection", "progress": 72, "status": "idle", "queue": _queue_depth(db, "planning")},
        {"name": "ExecutorAgent", "label": "Recovery workflow execution", "progress": 64, "status": "idle", "queue": _queue_depth(db, "execution")},
        {"name": "ConsensusAgent", "label": "Confidence consensus & gating", "progress": 58, "status": "idle", "queue": _queue_depth(db, "consensus")},
    ]
    data = {
        "generated_at": utcnow().isoformat(),
        "pipeline": {"total_recoveries": total_recoveries, "recovered": recovered, "recovery_rate": round(recovered / total_recoveries * 100, 2) if total_recoveries else 0.0},
        "agents": agents,
    }
    return success(data, agents=[a["name"] for a in agents], latency_ms=elapsed_ms(started))


def _queue_depth(db: Session, stage: str) -> int:
    pending = (RecoveryStatus.PENDING.value, RecoveryStatus.PLANNED.value, RecoveryStatus.IN_PROGRESS.value)
    return (
        db.query(func.count(RecoveryRecord.id))
        .filter(RecoveryRecord.status.in_(pending))
        .scalar() or 0
    )


@router.websocket("/metrics-stream")
async def metrics_stream(websocket: WebSocket, api_key: Optional[str] = None) -> None:
    from app.core.config import get_settings

    if not api_key or api_key not in get_settings().valid_api_keys:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    db: Optional[Session] = None
    try:
        db = next(get_db())
        while True:
            await websocket.send_json(
                {"status": "success", "data": collector.collect(db, period_days=30)}
            )
            await asyncio.sleep(10)
    except (WebSocketDisconnect, StopAsyncIteration):
        return
    finally:
        if db is not None:
            db.close()


@router.post("/export-report", dependencies=[Depends(require_api_key)])
async def export_report(
    request: Request,
    resource_type: str = Query(default="payment"),
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    cutoff = utcnow() - timedelta(days=period_days)
    rows = (
        db.query(RecoveryRecord, PaymentRecord)
        .join(PaymentRecord, PaymentRecord.id == RecoveryRecord.payment_id)
        .filter(RecoveryRecord.created_at >= cutoff)
        .order_by(RecoveryRecord.created_at.desc())
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "payment_id",
            "order_id",
            "strategy",
            "status",
            "attempts",
            "expected_amount_inr",
            "recovered_amount_inr",
            "cost_inr",
            "created_at",
            "updated_at",
        ]
    )
    for recovery, payment in rows:
        writer.writerow(
            [
                payment.id,
                payment.order_id,
                recovery.strategy,
                recovery.status,
                recovery.attempts,
                paise_to_rupees(recovery.expected_amount_paise),
                paise_to_rupees(recovery.recovered_amount_paise),
                paise_to_rupees(recovery.cost_paise),
                recovery.created_at.isoformat(),
                recovery.updated_at.isoformat(),
            ]
        )
    data = {
        "filename": f"drishti_{resource_type}_report_{utcnow().strftime('%Y%m%d')}.csv",
        "rows": len(rows),
        "content_type": "text/csv",
        "csv": buffer.getvalue(),
    }
    return success(data, agents=["AuditTrail"], latency_ms=elapsed_ms(started))


# ---------------------------------------------------------------------------
# Live data endpoints (synthetic, continuously updating)
# ---------------------------------------------------------------------------

@router.get("/live-metrics", dependencies=[Depends(require_api_key)])
async def get_live_metrics(request: Request) -> dict:
    """Return live aggregate KPI metrics from the background data generator."""
    from app.services.live_data import live_data

    started = measure()
    data = live_data.get_live_metrics()
    return success(data, latency_ms=elapsed_ms(started))


@router.get("/live-agent-status", dependencies=[Depends(require_api_key)])
async def get_live_agent_status(request: Request) -> dict:
    """Return live agent processing status from the background data generator."""
    from app.services.live_data import live_data

    started = measure()
    data = live_data.get_agent_status()
    return success(data, latency_ms=elapsed_ms(started))


@router.get("/live-payments", dependencies=[Depends(require_api_key)])
async def get_live_payments(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: Optional[str] = Query(default=None),
) -> dict:
    """Return live payment list from the background data generator."""
    from app.services.live_data import live_data

    started = measure()
    data = live_data.get_payments_list(limit=limit, status=status)
    return success(data, latency_ms=elapsed_ms(started))
