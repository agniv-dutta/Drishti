"""Recoveries v1 router: list attempts, timeline, execute, status, stop."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.agents import get_supervisor
from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import PaymentRecord, RecoveryRecord
from app.database.session import get_db
from app.models.recovery import RecoveryStatus
from app.utils.formatters import paise_to_rupees

router = APIRouter(prefix="/recoveries", tags=["recoveries"], dependencies=[Depends(require_api_key)])

STOPPABLE = (RecoveryStatus.PENDING.value, RecoveryStatus.PLANNED.value, RecoveryStatus.IN_PROGRESS.value)


def _rupees(amount_paise: int) -> float:
    return round(amount_paise / 100.0, 2)


def _serialize(recovery: RecoveryRecord) -> dict:
    return {
        "recovery_id": recovery.id,
        "payment_id": recovery.payment_id,
        "strategy": recovery.strategy,
        "status": recovery.status,
        "priority": recovery.priority,
        "risk_score": recovery.risk_score,
        "expected_amount": _rupees(recovery.expected_amount_paise),
        "recovered_amount": _rupees(recovery.recovered_amount_paise),
        "cost": _rupees(recovery.cost_paise),
        "attempts": recovery.attempts,
        "max_attempts": recovery.max_attempts,
        "executed_at": recovery.executed_at.isoformat() if recovery.executed_at else None,
        "completed_at": recovery.completed_at.isoformat() if recovery.completed_at else None,
        "created_at": recovery.created_at.isoformat(),
        "updated_at": recovery.updated_at.isoformat(),
    }


@router.get("")
async def list_recoveries(
    request: Request,
    status: Optional[str] = Query(default=None),
    strategy: Optional[str] = Query(default=None),
    payment_id: Optional[str] = Query(default=None),
    period_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    query = db.query(RecoveryRecord)
    if status:
        query = query.filter(RecoveryRecord.status == status)
    if strategy:
        query = query.filter(RecoveryRecord.strategy == strategy)
    if payment_id:
        query = query.filter(RecoveryRecord.payment_id == payment_id)
    query = query.filter(RecoveryRecord.created_at >= _cutoff(period_days))

    total = query.count()
    rows = query.order_by(RecoveryRecord.created_at.desc()).offset(offset).limit(limit).all()
    data = {"total": total, "count": len(rows), "offset": offset, "limit": limit, "recoveries": [_serialize(r) for r in rows]}
    return success(data, agents=["ExecutorAgent"], latency_ms=elapsed_ms(started))


def _cutoff(period_days: int):
    from app.models.payment import utcnow
    from datetime import timedelta

    return utcnow() - timedelta(days=period_days)


@router.get("/{recovery_id}")
async def get_recovery(
    recovery_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    recovery = db.get(RecoveryRecord, recovery_id)
    if recovery is None:
        return error("RECOVERY_NOT_FOUND", f"recovery '{recovery_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    data = {
        **_serialize(recovery),
        "analysis": recovery.analysis_json,
        "plan": recovery.plan_json,
        "result": recovery.result_json,
    }
    return success(data, agents=["ExecutorAgent"], latency_ms=elapsed_ms(started))


@router.get("/{recovery_id}/status")
async def get_recovery_status(
    recovery_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    recovery = db.get(RecoveryRecord, recovery_id)
    if recovery is None:
        return error("RECOVERY_NOT_FOUND", f"recovery '{recovery_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    data = {
        "recovery_id": recovery.id,
        "payment_id": recovery.payment_id,
        "status": recovery.status,
        "attempts": recovery.attempts,
        "max_attempts": recovery.max_attempts,
        "recovered_amount": _rupees(recovery.recovered_amount_paise),
        "expected_amount": _rupees(recovery.expected_amount_paise),
        "is_running": recovery.status in STOPPABLE,
        "updated_at": recovery.updated_at.isoformat(),
    }
    return success(data, agents=["ExecutorAgent"], latency_ms=elapsed_ms(started))


@router.get("/{recovery_id}/timeline")
async def get_recovery_timeline(
    recovery_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    recovery = db.get(RecoveryRecord, recovery_id)
    if recovery is None:
        return error("RECOVERY_NOT_FOUND", f"recovery '{recovery_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    events = []
    plan = recovery.plan_json or {}
    result = recovery.result_json or {}
    steps = plan.get("steps", [])
    for idx, step in enumerate(steps):
        match = next((o for o in result.get("outcomes", []) if o.get("channel") == step.get("channel")), None)
        events.append(
            {
                "order": idx + 1,
                "channel": step.get("channel"),
                "delay_minutes": step.get("delay_minutes") or step.get("delay"),
                "status": (match or {}).get("status"),
                "cost_inr": _rupees((match or {}).get("cost_incurred_paise", 0)),
            }
        )
    data = {
        "recovery_id": recovery.id,
        "payment_id": recovery.payment_id,
        "strategy": recovery.strategy,
        "status": recovery.status,
        "created_at": recovery.created_at.isoformat(),
        "executed_at": recovery.executed_at.isoformat() if recovery.executed_at else None,
        "events": events,
    }
    return success(data, agents=["ExecutorAgent"], latency_ms=elapsed_ms(started))


@router.post("/{recovery_id}/execute")
async def execute_recovery(
    recovery_id: str,
    request: Request,
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    try:
        result, recovery = await get_supervisor().execute_recovery(db, plan_id=recovery_id, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        return error("EXECUTE_FAILED", str(exc), status_code=404, latency_ms=elapsed_ms(started), request=request)

    result_json = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    if dry_run:
        db.rollback()
    else:
        db.commit()
    data = {
        "recovery_id": recovery.id,
        "payment_id": recovery.payment_id,
        "status": recovery.status,
        "success": bool(getattr(result, "success", False)),
        "recovered_amount": _rupees(recovery.recovered_amount_paise),
        "dry_run": dry_run,
        "execution": result_json,
    }
    return success(data, agents=["ExecutorAgent"], latency_ms=elapsed_ms(started))


@router.post("/{recovery_id}/stop")
async def stop_recovery(
    recovery_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    recovery = db.get(RecoveryRecord, recovery_id)
    if recovery is None:
        return error("RECOVERY_NOT_FOUND", f"recovery '{recovery_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    if recovery.status not in STOPPABLE:
        return error(
            "RECOVERY_NOT_STOPPABLE",
            f"recovery '{recovery_id}' is {recovery.status} and cannot be stopped",
            status_code=409,
            latency_ms=elapsed_ms(started),
            request=request,
        )
    recovery.status = RecoveryStatus.FAILED.value
    db.commit()
    data = {"recovery_id": recovery.id, "payment_id": recovery.payment_id, "status": recovery.status, "stopped": True}
    return success(data, agents=["SupervisorAgent"], latency_ms=elapsed_ms(started))
