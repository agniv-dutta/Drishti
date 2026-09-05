"""Agents v1 router: status, orchestration view, batch processing, decision tree, live stream."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents import get_supervisor
from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import PaymentRecord, RecoveryRecord
from app.database.session import get_db
from app.models.payment import utcnow
from app.models.recovery import RecoveryStatus

router = APIRouter(prefix="/agents", tags=["agents"])

AGENTS = [
    {"key": "analyzer", "name": "PaymentAnalyzer", "description": "Failure cause detection and risk scoring"},
    {"key": "strategist", "name": "StrategySelector", "description": "Recovery strategy and channel selection"},
    {"key": "executor", "name": "ExecutorAgent", "description": "Executes recovery workflow steps"},
    {"key": "consensus", "name": "ConsensusAgent", "description": "Gates strategies behind multi-persona confidence"},
]


def _recovery_counts(db: Session) -> dict:
    statuses = {s: (db.query(func.count(RecoveryRecord.id)).filter(RecoveryRecord.status == s).scalar() or 0) for s in [v.value for v in RecoveryStatus]}
    return statuses


@router.get("/status", dependencies=[Depends(require_api_key)])
async def agent_status(db: Session = Depends(get_db)) -> dict:
    started = measure()
    counts = _recovery_counts(db)
    pending = sum(counts.get(s, 0) for s in (RecoveryStatus.PENDING.value, RecoveryStatus.PLANNED.value, RecoveryStatus.IN_PROGRESS.value))
    total = sum(counts.values())
    statuses = []
    for agent in AGENTS:
        weight = {"analyzer": 1.0, "strategist": 0.75, "executor": 0.6, "consensus": 0.5}[agent["key"]]
        statuses.append(
            {
                **agent,
                "progress": round(weight * 100),
                "status": "running" if pending else "idle",
                "queue_depth": pending,
                "last_active": None,
            }
        )
    data = {
        "generated_at": utcnow().isoformat(),
        "total_recoveries": total,
        "queue_depth": pending,
        "agents": statuses,
    }
    return success(data, agents=[a["name"] for a in AGENTS], latency_ms=elapsed_ms(started))


@router.get("/operations", dependencies=[Depends(require_api_key)])
async def agent_operations(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    counts = _recovery_counts(db)
    recent = (
        db.query(RecoveryRecord)
        .order_by(RecoveryRecord.updated_at.desc())
        .limit(limit)
        .all()
    )
    operations = []
    for recovery in recent:
        operations.append(
            {
                "recovery_id": recovery.id,
                "payment_id": recovery.payment_id,
                "strategy": recovery.strategy,
                "status": recovery.status,
                "attempts": recovery.attempts,
                "updated_at": recovery.updated_at.isoformat(),
            }
        )
    data = {
        "agent_activity": [{"agent": a["name"], "state": "idle", "last_tick": None} for a in AGENTS],
        "recovery_pipeline": counts,
        "recent_recoveries": operations,
    }
    return success(data, agents=[a["name"] for a in AGENTS], latency_ms=elapsed_ms(started))


@router.post("/batch-process", dependencies=[Depends(require_api_key)])
async def batch_process(
    request: Request,
    payment_ids: Optional[List[str]] = None,
    lookback_hours: int = Query(default=24, ge=1, le=720),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    query = db.query(PaymentRecord).filter(PaymentRecord.status == "failed")
    if payment_ids:
        query = query.filter(PaymentRecord.id.in_(payment_ids))
    payments = query.order_by(PaymentRecord.created_at.desc()).all()
    if not payments:
        return success(
            {"processed": 0, "accepted": [], "rejected": []},
            agents=["SupervisorAgent"],
            latency_ms=elapsed_ms(started),
        )

    supervisor = get_supervisor()
    results = []
    for payment in payments:
        try:
            if not dry_run:
                plan, recovery = await supervisor.build_plan(db, payment.id)
                recovery_id = recovery.id if recovery else None
            else:
                recovery_id = None
            results.append({"payment_id": payment.id, "status": "accepted", "recovery_id": recovery_id})
        except Exception as exc:  # noqa: BLE001
            results.append({"payment_id": payment.id, "status": "rejected", "error": str(exc)})
    db.commit()
    accepted = [r for r in results if r["status"] == "accepted"]
    data = {
        "processed": len(results),
        "pipeline_started": not dry_run,
        "accepted": accepted,
        "rejected": [r for r in results if r["status"] == "rejected"],
    }
    return success(data, agents=["SupervisorAgent", "PaymentAnalyzer"], latency_ms=elapsed_ms(started))


@router.get("/decisions/{payment_id}", dependencies=[Depends(require_api_key)])
async def agent_decisions(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    recovery = (
        db.query(RecoveryRecord)
        .filter(RecoveryRecord.payment_id == payment_id)
        .order_by(RecoveryRecord.created_at.desc())
        .first()
    )
    analysis = (recovery.analysis_json or {}) if recovery else {}
    plan = (recovery.plan_json or {}) if recovery else {}
    decision_tree = []
    decision_tree.append(
        {
            "agent": "PaymentAnalyzer",
            "stage": "analyze",
            "output": {"failure_reason": analysis.get("failure_reason"), "confidence": analysis.get("confidence"), "risk_score": analysis.get("risk_score")},
            "selected": True,
        }
    )
    decision_tree.append(
        {
            "agent": "StrategySelector",
            "stage": "strategize",
            "output": {"strategy": plan.get("strategy"), "steps_count": len(plan.get("steps", []))},
            "selected": bool(plan),
        }
    )
    decision_tree.append(
        {
            "agent": "ConsensusAgent",
            "stage": "gate",
            "output": {"winner": (plan.get("rationale") or {}).get("created_by") if isinstance(plan.get("rationale"), dict) else None, "confirmed": bool(recovery)},
            "selected": bool(recovery),
        }
    )
    data = {
        "payment_id": payment.id,
        "amount": round(payment.amount_paise / 100.0, 2),
        "final_recovery_status": recovery.status if recovery else None,
        "decision_tree": decision_tree,
    }
    return success(data, agents=["PaymentAnalyzer", "StrategySelector", "ConsensusAgent"], latency_ms=elapsed_ms(started))


@router.websocket("/stream")
async def agent_stream(websocket: WebSocket, api_key: Optional[str] = None) -> None:
    from app.core.config import get_settings

    if not api_key or api_key not in get_settings().valid_api_keys:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    db: Optional[Session] = None
    try:
        db = next(get_db())
        while True:
            counts = _recovery_counts(db)
            payload = {
                "status": "success",
                "data": {
                    "tick": utcnow().isoformat(),
                    "agents": [{"name": a["name"], "state": "idle"} for a in AGENTS],
                    "recovery_pipeline": counts,
                },
            }
            await websocket.send_json(payload)
            await asyncio.sleep(5)
    except (WebSocketDisconnect, StopAsyncIteration):
        return
    finally:
        if db is not None:
            db.close()
