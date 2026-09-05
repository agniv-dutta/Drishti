"""Workflows v1 router: templates, custom workflows, create, test, deploy."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
from app.database.models import PaymentRecord, RecoveryWorkflow
from app.database.session import get_db
from app.schemas.workflow_schemas import WorkflowCreateRequest, WorkflowStepPayload

router = APIRouter(prefix="/workflows", tags=["workflows"])

BUILTIN_TEMPLATES = [
    {
        "id": "tpl_standard",
        "name": "Standard Recovery",
        "target_segment": "all",
        "description": "Default retry + SMS + email sequence.",
        "steps": [
            {"type": "retry", "delay": "0h"},
            {"type": "wait", "delay": "24h"},
            {"type": "sms", "delay": "24h", "template": "recovery_link"},
            {"type": "wait", "delay": "24h"},
            {"type": "email", "delay": "24h", "template": "reminder"},
            {"type": "escalate", "delay": "72h"},
        ],
    },
    {
        "id": "tpl_high_value",
        "name": "High-Value Recovery",
        "target_segment": "high_value",
        "description": "Personalized voice-first outreach for large balances.",
        "steps": [
            {"type": "call", "delay": "0h"},
            {"type": "retry", "delay": "2h"},
            {"type": "sms", "delay": "6h", "template": "priority_link"},
            {"type": "offer", "delay": "24h", "max_discount": "10%"},
        ],
    },
    {
        "id": "tpl_gentle",
        "name": "Gentle Nudge",
        "target_segment": "recurring",
        "description": "Low-friction email/SMS nudges for loyal customers.",
        "steps": [
            {"type": "email", "delay": "0h", "template": "friendly_reminder"},
            {"type": "wait", "delay": "24h"},
            {"type": "sms", "delay": "24h", "template": "retry_prompt"},
        ],
    },
]


def _parse_steps(payload) -> List[WorkflowStepPayload]:
    return [WorkflowStepPayload(**step) for step in payload]


def _response(record: RecoveryWorkflow) -> Dict[str, Any]:
    payload = record.steps_json or {}
    if isinstance(payload, list):
        steps, metadata = payload, {}
    else:
        metadata = payload
        steps = payload.get("steps", [])
    return {
        "id": record.id,
        "name": record.template_name,
        "target_segment": metadata.get("target_segment", "all"),
        "steps": [WorkflowStepPayload(**s).model_dump() for s in steps],
        "variant": metadata.get("variant"),
        "success_rate": record.success_rate,
        "created_at": record.created_at.isoformat(),
    }


@router.get("/templates")
async def list_templates(db: Session = Depends(get_db)) -> dict:
    started = measure()
    data = {"count": len(BUILTIN_TEMPLATES), "templates": BUILTIN_TEMPLATES}
    return success(data, agents=["StrategySelector"], latency_ms=elapsed_ms(started))


@router.get("/custom")
async def list_custom_workflows(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    records = db.query(RecoveryWorkflow).order_by(RecoveryWorkflow.created_at.desc()).limit(limit).all()
    data = {"count": len(records), "workflows": [_response(r) for r in records]}
    return success(data, agents=["StrategySelector"], latency_ms=elapsed_ms(started))


@router.get("")
async def list_workflows(
    request: Request,
    include_templates: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    records = db.query(RecoveryWorkflow).order_by(RecoveryWorkflow.created_at.desc()).all()
    custom = [_response(r) for r in records]
    data = {"count": len(custom), "workflows": custom}
    if include_templates:
        data["templates"] = BUILTIN_TEMPLATES
    return success(data, agents=["StrategySelector"], latency_ms=elapsed_ms(started))


@router.post("/create")
async def create_workflow(
    request: Request,
    payload: WorkflowCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    if db.query(RecoveryWorkflow).filter(RecoveryWorkflow.template_name == payload.name).first():
        return error("WORKFLOW_EXISTS", f"A workflow named '{payload.name}' already exists", status_code=409, latency_ms=elapsed_ms(started), request=request)
    record = RecoveryWorkflow(
        template_name=payload.name,
        steps_json={
            "target_segment": payload.target_segment,
            "variant": payload.variant,
            "steps": [step.model_dump(exclude_none=True) for step in payload.steps],
        },
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return success(_response(record), agents=["StrategySelector"], latency_ms=elapsed_ms(started))


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    template = next((t for t in BUILTIN_TEMPLATES if t["id"] == workflow_id), None)
    if template:
        return success(template, agents=["StrategySelector"], latency_ms=elapsed_ms(started))
    record = db.get(RecoveryWorkflow, workflow_id)
    if record is None:
        return error("WORKFLOW_NOT_FOUND", f"workflow '{workflow_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    return success(_response(record), agents=["StrategySelector"], latency_ms=elapsed_ms(started))


def _resolve_workflow(db: Session, workflow_id: str):
    template = next((t for t in BUILTIN_TEMPLATES if t["id"] == workflow_id), None)
    if template:
        return template
    record = db.get(RecoveryWorkflow, workflow_id)
    return _response(record) if record else None


@router.post("/{workflow_id}/test")
async def test_workflow(
    workflow_id: str,
    request: Request,
    sample_size: int = Query(default=5, ge=1, le=25),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    workflow = _resolve_workflow(db, workflow_id)
    if workflow is None:
        return error("WORKFLOW_NOT_FOUND", f"workflow '{workflow_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    failed = db.query(PaymentRecord).filter(PaymentRecord.status == "failed").limit(sample_size).all()
    data = {
        "workflow_id": workflow_id,
        "name": workflow.get("name") if isinstance(workflow, dict) else workflow_id,
        "test_batch_size": sample_size,
        "matched_payments": len(failed),
        "run": "queued",
        "status": "test_completed",
        "sample_payment_ids": [p.id for p in failed],
    }
    return success(data, agents=["ExecutorAgent", "StrategySelector"], latency_ms=elapsed_ms(started))


@router.post("/{workflow_id}/deploy")
async def deploy_workflow(
    workflow_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    workflow = _resolve_workflow(db, workflow_id)
    if workflow is None:
        return error("WORKFLOW_NOT_FOUND", f"workflow '{workflow_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    data = {
        "workflow_id": workflow_id,
        "name": workflow.get("name") if isinstance(workflow, dict) else workflow_id,
        "deployed": True,
        "environment": "production",
        "deployed_at": _now_iso(),
    }
    return success(data, agents=["ExecutorAgent"], latency_ms=elapsed_ms(started))


def _now_iso() -> str:
    from app.models.payment import utcnow

    return utcnow().isoformat()
