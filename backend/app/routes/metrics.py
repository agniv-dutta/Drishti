"""Metrics endpoints: recovery-rate and cost-analysis."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.cache.redis_client import get_cache
from app.core.security import require_api_key
from app.database.models import RecoveryRecord
from app.database.session import get_db
from app.models.payment import utcnow
from app.models.recovery import RecoveryStatus
from app.schemas.metrics_schemas import (
    ChannelStat,
    CostAnalysisResponse,
    CostItem,
    RecoveryRateResponse,
)
from app.utils.formatters import paise_to_rupees

router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(require_api_key)])


def _window_records(db: Session, period_days: int) -> List[RecoveryRecord]:
    cutoff = utcnow() - timedelta(days=period_days)
    return (
        db.query(RecoveryRecord)
        .filter(RecoveryRecord.created_at >= cutoff)
        .all()
    )


@router.get("/recovery-rate", response_model=RecoveryRateResponse)
async def recovery_rate(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> RecoveryRateResponse:
    cache = await get_cache()
    cache_key = f"metrics:recovery-rate:{period_days}"
    cached = await cache.get_json(cache_key)
    if cached:
        return RecoveryRateResponse(**cached)

    records = _window_records(db, period_days)
    succeeded = [r for r in records if r.status == RecoveryStatus.SUCCEEDED.value]
    failed = [r for r in records if r.status == RecoveryStatus.FAILED.value]
    pending = [
        r for r in records
        if r.status in (RecoveryStatus.PENDING.value, RecoveryStatus.PLANNED.value,
                        RecoveryStatus.IN_PROGRESS.value)
    ]

    total_cost_success_paise = sum(r.cost_paise for r in succeeded)
    channel_agg: Dict[str, Dict[str, int]] = {}
    for record in records:
        for outcome in (record.result_json or {}).get("outcomes", []):
            if outcome.get("status") == "skipped":
                continue
            bucket = channel_agg.setdefault(
                outcome.get("channel", "unknown"),
                {"attempts": 0, "successes": 0, "cost": 0, "recovered": 0},
            )
            bucket["attempts"] += 1
            if outcome.get("status") == "succeeded":
                bucket["successes"] += 1
            bucket["cost"] += outcome.get("cost_incurred_paise", 0)
            bucket["recovered"] += outcome.get("recovered_amount_paise", 0)

    response = RecoveryRateResponse(
        period_days=period_days,
        total_attempts=len(records),
        successful_recoveries=len(succeeded),
        failed_recoveries=len(failed),
        pending_recoveries=len(pending),
        recovery_rate_pct=round(len(succeeded) / len(records) * 100, 2) if records else 0.0,
        attempted_amount_inr=round(paise_to_rupees(sum(r.expected_amount_paise for r in records)), 2),
        recovered_amount_inr=round(paise_to_rupees(sum(r.recovered_amount_paise for r in records)), 2),
        avg_cost_per_success_inr=(
            round(paise_to_rupees(total_cost_success_paise / len(succeeded)), 2)
            if succeeded else 0.0
        ),
        generated_at=utcnow(),
        by_channel=[
            ChannelStat(
                channel=channel,
                attempts=data["attempts"],
                successes=data["successes"],
                success_rate_pct=round(data["successes"] / data["attempts"] * 100, 2)
                if data["attempts"] else 0.0,
                cost_inr=paise_to_rupees(data["cost"]),
                recovered_inr=paise_to_rupees(data["recovered"]),
            )
            for channel, data in sorted(channel_agg.items())
        ],
    )
    await cache.set_json(cache_key, response.model_dump(mode="json"), ttl=60)
    return response


@router.get("/cost-analysis", response_model=CostAnalysisResponse)
async def cost_analysis(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> CostAnalysisResponse:
    cache = await get_cache()
    cache_key = f"metrics:cost-analysis:{period_days}"
    cached = await cache.get_json(cache_key)
    if cached:
        return CostAnalysisResponse(**cached)

    records = _window_records(db, period_days)
    items: List[CostItem] = []
    totals = {"cost": 0, "revenue": 0}

    for channel in sorted({c for r in records for c in _channels_used(r)}):
        executions = 0
        cost_paise = 0
        revenue_paise = 0
        for record in records:
            for outcome in (record.result_json or {}).get("outcomes", []):
                if outcome.get("channel") != channel or outcome.get("status") == "skipped":
                    continue
                executions += 1
                cost_paise += outcome.get("cost_incurred_paise", 0)
                revenue_paise += outcome.get("recovered_amount_paise", 0)

        cost_inr = paise_to_rupees(cost_paise)
        revenue_inr = paise_to_rupees(revenue_paise)
        totals["cost"] += cost_paise
        totals["revenue"] += revenue_paise
        items.append(
            CostItem(
                channel=channel,
                executions=executions,
                total_cost_inr=round(cost_inr, 2),
                avg_cost_inr=round(cost_inr / executions, 2) if executions else 0.0,
                revenue_attributed_inr=round(revenue_inr, 2),
                roi_pct=round((revenue_inr - cost_inr) / cost_inr * 100, 2) if cost_inr > 0 else None,
            )
        )

    total_cost_inr = paise_to_rupees(totals["cost"])
    total_revenue_inr = paise_to_rupees(totals["revenue"])
    response = CostAnalysisResponse(
        period_days=period_days,
        total_cost_inr=round(total_cost_inr, 2),
        total_recovered_inr=round(total_revenue_inr, 2),
        net_value_inr=round(total_revenue_inr - total_cost_inr, 2),
        roi_pct=(
            round((total_revenue_inr - total_cost_inr) / total_cost_inr * 100, 2)
            if total_cost_inr > 0 else None
        ),
        items=items,
        generated_at=utcnow(),
    )
    await cache.set_json(cache_key, response.model_dump(mode="json"), ttl=60)
    return response


def _channels_used(record: RecoveryRecord) -> set:
    return {
        outcome.get("channel")
        for outcome in (record.result_json or {}).get("outcomes", [])
        if outcome.get("channel")
    }
