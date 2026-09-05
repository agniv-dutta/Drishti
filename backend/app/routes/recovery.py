"""Recovery endpoints: detect, plan, execute, detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import (
    AuditSupervisorAgent,
    ExecutionOrchestratorAgent,
    PaymentAnalyzerAgent,
    StrategySelectorAgent,
    PaymentNotFoundError,
    RecoveryNotFoundError,
    SupervisorError,
    get_supervisor,
)
from app.core.security import require_api_key
from app.database.models import RecoveryRecord
from app.database.models import PaymentRecord
from app.database.session import get_db
from app.models.recovery import ExecutionResult, RecoveryPlan
from app.schemas.recovery_schemas import (
    DetectRequest,
    DetectResponse,
    ExecuteRequest,
    ExecuteResponse,
    ExecuteSummary,
    PlanRequest,
    PlanResponse,
    RecoveryDetailResponse,
)
from app.utils.formatters import paise_to_rupees

router = APIRouter(prefix="/recovery", tags=["recovery"], dependencies=[Depends(require_api_key)])


@router.post("/start")
async def start_recovery(
    payment_id: str,
    db: Session = Depends(get_db),
):
    """Run the direct agent chain: analyze, select, execute, and audit."""
    record = db.get(PaymentRecord, payment_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"payment '{payment_id}' not found")
    payment = record.to_domain()
    analysis = await PaymentAnalyzerAgent().analyze(payment)
    recommendation = await StrategySelectorAgent().select_strategy(payment, analysis)
    execution = await ExecutionOrchestratorAgent().execute(payment, recommendation)
    audit = await AuditSupervisorAgent().gate_and_log(payment, analysis, recommendation, execution)
    return {
        "payment_id": payment_id,
        "chain": [
            {"agent": "PaymentAnalyzer", "result": analysis.model_dump(mode="json")},
            {"agent": "StrategySelector", "result": recommendation.model_dump(mode="json")},
            {"agent": "ExecutionOrchestrator", "result": execution.model_dump(mode="json")},
            {"agent": "AuditSupervisor", "result": audit.model_dump(mode="json")},
        ],
        "final_status": audit.approval_status,
        "timestamp": audit.timestamp,
    }


@router.post("/detect", response_model=DetectResponse)
async def detect_recoveries(
    payload: DetectRequest,
    db: Session = Depends(get_db),
) -> DetectResponse:
    """Scan failed payments and surface recovery candidates (optionally persisted)."""
    try:
        return await get_supervisor().detect_candidates(db, payload)
    except SupervisorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plan", response_model=PlanResponse)
async def build_recovery_plan(
    payload: PlanRequest,
    db: Session = Depends(get_db),
) -> PlanResponse:
    """Analyze + strategize for one payment; persists a PLANNED recovery record."""
    try:
        plan, record = await get_supervisor().build_plan(
            db, payload.payment_id, override_strategy=payload.override_strategy,
            persist=not payload.dry_run,
        )
    except PaymentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlanResponse(plan=plan, persisted=record is not None)


@router.post("/execute", response_model=ExecuteResponse)
async def execute_recovery(
    payload: ExecuteRequest,
    db: Session = Depends(get_db),
) -> ExecuteResponse:
    """Execute (or dry-run) the latest plan for a payment, or an explicit plan id."""
    try:
        result, _ = await get_supervisor().execute_recovery(
            db,
            plan_id=payload.plan_id,
            payment_id=payload.payment_id,
            dry_run=payload.dry_run,
        )
    except (PaymentNotFoundError, RecoveryNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    successes = 1 if result.success else 0
    summary = ExecuteSummary(
        plans_executed=1,
        successes=successes,
        failures=1 - successes,
        total_cost_paise=result.total_cost_paise,
        total_recovered_paise=result.recovered_amount_paise,
        net_value_paise=result.net_value_paise,
    )
    return ExecuteResponse(results=[result], summary=summary)


@router.get("/{recovery_id}", response_model=RecoveryDetailResponse)
async def get_recovery(
    recovery_id: str,
    db: Session = Depends(get_db),
) -> RecoveryDetailResponse:
    record = db.get(RecoveryRecord, recovery_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"recovery '{recovery_id}' not found")
    return RecoveryDetailResponse(
        recovery_id=record.id,
        payment_id=record.payment_id,
        strategy=record.strategy,
        status=record.status,
        risk_score=record.risk_score,
        expected_amount_inr=paise_to_rupees(record.expected_amount_paise),
        recovered_amount_inr=paise_to_rupees(record.recovered_amount_paise),
        cost_inr=paise_to_rupees(record.cost_paise),
        attempts=record.attempts,
        max_attempts=record.max_attempts,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_plan=RecoveryPlan(**record.plan_json) if record.plan_json else None,
        last_result=ExecutionResult(**record.result_json) if record.result_json else None,
    )
