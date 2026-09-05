"""Direct agent endpoints for integrations that already have an analysis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.payment_analyzer import AnalysisResult
from app.agents.audit_supervisor import AuditResult, AuditSupervisorAgent
from app.agents.execution_orchestrator import ExecutionOrchestratorAgent, ExecutionResult
from app.agents.strategy_selector import StrategyRecommendation, StrategySelectorAgent
from app.core.logging_config import get_audit_trail
from app.core.security import require_api_key
from app.database.models import PaymentRecord
from app.database.session import get_db

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(require_api_key)])


class SelectStrategyRequest(BaseModel):
    payment_id: str
    analysis: AnalysisResult


class ExecuteRecoveryRequest(BaseModel):
    payment_id: str
    recommendation: StrategyRecommendation


class AuditGateRequest(BaseModel):
    payment_id: str
    analysis: AnalysisResult
    recommendation: StrategyRecommendation
    execution: ExecutionResult


@router.post("/select-strategy", response_model=StrategyRecommendation)
async def select_strategy(
    payload: SelectStrategyRequest,
    db: Session = Depends(get_db),
) -> StrategyRecommendation:
    record = db.get(PaymentRecord, payload.payment_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"payment '{payload.payment_id}' not found")

    recommendation = await StrategySelectorAgent().select_strategy(
        record.to_domain(), payload.analysis
    )
    get_audit_trail().record(
        event_type="strategy_selected",
        actor="StrategySelector",
        resource_type="payment",
        resource_id=payload.payment_id,
        outcome=recommendation.primary_strategy,
        details={
            "confidence": recommendation.primary_confidence,
            "alternatives": recommendation.alternatives,
        },
    )
    return recommendation


@router.post("/execute", response_model=ExecutionResult)
async def execute_recovery(
    payload: ExecuteRecoveryRequest,
    db: Session = Depends(get_db),
) -> ExecutionResult:
    record = db.get(PaymentRecord, payload.payment_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"payment '{payload.payment_id}' not found")
    return await ExecutionOrchestratorAgent().execute(record.to_domain(), payload.recommendation)


@router.post("/audit-gate", response_model=AuditResult)
async def audit_and_gate(
    payload: AuditGateRequest,
    db: Session = Depends(get_db),
) -> AuditResult:
    record = db.get(PaymentRecord, payload.payment_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"payment '{payload.payment_id}' not found")
    return await AuditSupervisorAgent().gate_and_log(
        record.to_domain(), payload.analysis, payload.recommendation, payload.execution
    )