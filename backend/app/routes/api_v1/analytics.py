"""Analytics v1 router: funnel, strategy performance, revenue trend, cost, model, alerts."""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, measure, success
from app.core.security import require_api_key
from app.database.models import PaymentRecord, RecoveryRecord
from app.database.session import get_db
from app.metrics.collector import MetricsCollector
from app.models.payment import utcnow
from app.models.recovery import RecoveryStatus
from app.utils.formatters import paise_to_rupees

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_api_key)])

collector = MetricsCollector()

_FUNNEL_STAGES = ["ingested", "analyzed", "strategized", "executed", "recovered"]
_STRATEGY_LABELS = {
    "smart_retry": "Retry",
    "sms_link": "SMS",
    "voice_call": "Call",
    "dynamic_offer": "Offer",
    "email_sequence": "Email",
    "crm_escalation": "CRM Escalation",
}


def _cutoff(period_days: int):
    return utcnow() - timedelta(days=period_days)


@router.get("/recovery-funnel")
async def recovery_funnel(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    records = db.query(RecoveryRecord).filter(RecoveryRecord.created_at >= _cutoff(period_days)).all()
    recovered = [r for r in records if r.recovered_amount_paise > 0]
    executed = [r for r in records if r.executed_at is not None]
    planned = [r for r in records if r.plan_json is not None]
    analyzed = [r for r in records if r.analysis_json is not None]
    ingested = db.query(func.count(PaymentRecord.id)).filter(PaymentRecord.created_at >= _cutoff(period_days)).scalar() or 0

    stages = [
        {"stage": "ingested", "count": ingested},
        {"stage": "analyzed", "count": len(analyzed)},
        {"stage": "strategized", "count": len(planned)},
        {"stage": "executed", "count": len(executed)},
        {"stage": "recovered", "count": len(recovered)},
    ]
    data = {
        "period_days": period_days,
        "stages": stages,
        "drop_offs": [
            {"from": stages[i]["stage"], "to": stages[i + 1]["stage"], "conversion_pct": round(stages[i + 1]["count"] / stages[i]["count"] * 100, 2) if stages[i]["count"] else 0.0}
            for i in range(len(stages) - 1)
        ],
    }
    return success(data, agents=["PaymentAnalyzer", "StrategySelector", "ExecutorAgent"], latency_ms=elapsed_ms(started))


@router.get("/strategy-performance")
async def strategy_performance(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    records = db.query(RecoveryRecord).filter(RecoveryRecord.created_at >= _cutoff(period_days)).all()
    bucket: Dict[str, Dict[str, int]] = {}
    for record in records:
        label = _STRATEGY_LABELS.get(record.strategy, record.strategy)
        entry = bucket.setdefault(label, {"strategy": record.strategy, "attempts": 0, "recovered": 0, "revenue_paise": 0})
        entry["attempts"] += 1
        if record.recovered_amount_paise > 0:
            entry["recovered"] += 1
            entry["revenue_paise"] += record.recovered_amount_paise
    items = [
        {
            "strategy": entry["strategy"],
            "label": label,
            "attempts": entry["attempts"],
            "recovered": entry["recovered"],
            "success_rate_pct": round(entry["recovered"] / entry["attempts"] * 100, 2) if entry["attempts"] else 0.0,
            "revenue_recovered_inr": round(paise_to_rupees(entry["revenue_paise"]), 2),
        }
        for label, entry in bucket.items()
    ]
    data = {"period_days": period_days, "strategies": items}
    return success(data, agents=["StrategySelector"], latency_ms=elapsed_ms(started))


@router.get("/revenue-trend")
async def revenue_trend(
    period_days: int = Query(default=30, ge=1, le=365),
    buckets: int = Query(default=10, ge=2, le=60),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    records = db.query(RecoveryRecord).filter(
        RecoveryRecord.created_at >= _cutoff(period_days), RecoveryRecord.recovered_amount_paise > 0
    ).all()
    from datetime import datetime

    now = utcnow()
    start = now - timedelta(days=period_days)
    span = max((now - start).total_seconds(), 1)
    series = [{"bucket": i + 1, "from": "", "amount_paise": 0} for i in range(buckets)]
    for record in records:
        ts = record.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=start.tzinfo)
        idx = min(int((ts - start).total_seconds() / span * buckets), buckets - 1)
        series[idx]["amount_paise"] += record.recovered_amount_paise
    for item in series:
        item["amount_recovered_inr"] = round(paise_to_rupees(item["amount_paise"]), 2)
        del item["amount_paise"]
    data = {"period_days": period_days, "buckets": buckets, "series": series}
    return success(data, agents=["MetricsCollector"], latency_ms=elapsed_ms(started))


@router.get("/cost-breakdown")
async def cost_breakdown(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    records = db.query(RecoveryRecord).filter(RecoveryRecord.created_at >= _cutoff(period_days)).all()
    channels: Dict[str, Dict[str, int]] = {}
    for record in records:
        for outcome in (record.result_json or {}).get("outcomes", []):
            if outcome.get("status") == "skipped":
                continue
            channel = outcome.get("channel", "unknown")
            entry = channels.setdefault(channel, {"executions": 0, "cost_paise": 0, "revenue_paise": 0})
            entry["executions"] += 1
            entry["cost_paise"] += outcome.get("cost_incurred_paise", 0)
            entry["revenue_paise"] += outcome.get("recovered_amount_paise", 0)
    items = []
    for channel, entry in channels.items():
        cost_inr = paise_to_rupees(entry["cost_paise"])
        revenue_inr = paise_to_rupees(entry["revenue_paise"])
        items.append(
            {
                "channel": channel,
                "executions": entry["executions"],
                "cost_inr": round(cost_inr, 2),
                "revenue_attributed_inr": round(revenue_inr, 2),
                "roi_pct": round((revenue_inr - cost_inr) / cost_inr * 100, 2) if cost_inr > 0 else None,
            }
        )
    total_cost_paise = sum(e["cost_paise"] for e in channels.values())
    total_revenue_paise = sum(e["revenue_paise"] for e in channels.values())
    data = {
        "period_days": period_days,
        "total_cost_inr": round(paise_to_rupees(total_cost_paise), 2),
        "total_recovered_inr": round(paise_to_rupees(total_revenue_paise), 2),
        "items": items,
    }
    return success(data, agents=["MetricsCollector"], latency_ms=elapsed_ms(started))


@router.get("/model-performance")
async def model_performance(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    metrics = collector.collect(db, period_days=period_days)
    data = {
        "period_days": period_days,
        "recovery_rate": round(metrics["recovery_rate"] * 100, 2),
        "false_positive_rate": round(metrics["false_positive_rate"], 4),
        "model_drift_score": round(metrics["model_drift_score"], 4),
        "drift_detected": metrics["model_drift_score"] > 0.1,
        "concepts": {"recovery_rate": round(metrics["recovery_rate"] * 100, 2)},
    }
    return success(data, agents=["ConsensusAgent"], latency_ms=elapsed_ms(started))


@router.get("/alerts")
async def analytics_alerts(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    metrics = collector.collect(db, period_days=period_days)
    alerts = []
    if metrics["recovery_rate"] < 0.3:
        alerts.append({"severity": "critical", "type": "recovery_rate_drop", "message": f"Recovery rate fell to {metrics['recovery_rate'] * 100:.1f}%", "period_days": period_days})
    if metrics["model_drift_score"] > 0.1:
        alerts.append({"severity": "warning", "type": "model_drift", "message": f"Model drift detected (MAE={metrics['model_drift_score']:.3f})", "period_days": period_days})
    if metrics["cost_per_recovery_inr"] > 50:
        alerts.append({"severity": "warning", "type": "cost_overrun", "message": f"Cost per recovery is ₹{metrics['cost_per_recovery_inr']:.2f}", "period_days": period_days})
    if metrics["false_positive_rate"] > 0.4:
        alerts.append({"severity": "warning", "type": "false_positive_high", "message": f"False positive rate is {metrics['false_positive_rate'] * 100:.0f}%", "period_days": period_days})
    data = {"period_days": period_days, "count": len(alerts), "alerts": alerts}
    return success(data, agents=["MetricsCollector", "ConsensusAgent"], latency_ms=elapsed_ms(started))
