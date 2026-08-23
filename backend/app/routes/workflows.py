"""Merchant workflow builder API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.database.models import RecoveryWorkflow
from app.database.session import get_db
from app.schemas.workflow_schemas import WorkflowCreateRequest, WorkflowListResponse, WorkflowResponse

router = APIRouter(prefix="/workflows", tags=["workflows"], dependencies=[Depends(require_api_key)])


def _response(record: RecoveryWorkflow) -> WorkflowResponse:
    payload = record.steps_json or {}
    if isinstance(payload, list):
        steps, metadata = payload, {}
    else:
        metadata = payload
        steps = payload.get("steps", [])
    return WorkflowResponse(
        id=record.id,
        name=record.template_name,
        target_segment=metadata.get("target_segment", "all"),
        steps=steps,
        variant=metadata.get("variant"),
        success_rate=record.success_rate,
        created_at=record.created_at,
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(db: Session = Depends(get_db)) -> WorkflowListResponse:
    records = db.query(RecoveryWorkflow).order_by(RecoveryWorkflow.created_at.desc()).all()
    return WorkflowListResponse(workflows=[_response(record) for record in records])


@router.post("/create", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(request: WorkflowCreateRequest, db: Session = Depends(get_db)) -> WorkflowResponse:
    if db.query(RecoveryWorkflow).filter(RecoveryWorkflow.template_name == request.name).first():
        raise HTTPException(status_code=409, detail="A workflow with this name already exists")
    record = RecoveryWorkflow(
        template_name=request.name,
        steps_json={
            "target_segment": request.target_segment,
            "variant": request.variant,
            "steps": [step.model_dump(exclude_none=True) for step in request.steps],
        },
    )
    db.add(record)
    db.flush()
    return _response(record)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str, db: Session = Depends(get_db)) -> WorkflowResponse:
    record = db.get(RecoveryWorkflow, workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _response(record)
