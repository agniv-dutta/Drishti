"""Request/response schemas for /recovery endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.recovery import (
    ExecutionResult,
    FailureReason,
    RecoveryPlan,
    RecoveryStrategy,
)


class DetectRequest(BaseModel):
    """POST /recovery/detect - find payments worth recovering."""

    payment_ids: Optional[List[str]] = Field(
        default=None, description="Explicit payment ids; omit to auto-scan"
    )
    lookback_hours: int = Field(default=72, ge=1, le=24 * 30)
    min_amount_inr: float = Field(default=0.0, ge=0)
    max_amount_inr: float = Field(default=10_000_000.0, gt=0)
    min_risk_score: float = Field(default=0.35, ge=0.0, le=1.0)
    persist_candidates: bool = Field(
        default=True, description="Create PENDING recovery records for candidates"
    )
    limit: int = Field(default=50, ge=1, le=500)


class DetectedCandidate(BaseModel):
    payment_id: str
    amount_inr: float
    failure_reason: FailureReason
    risk_score: float
    risk_band: str
    retryability: str
    recommended_strategy: RecoveryStrategy
    priority: str = Field(description="P0 (critical) .. P3 (low)")
    expected_recovery_inr: float


class DetectResponse(BaseModel):
    scanned_count: int
    candidate_count: int
    persisted_count: int = 0
    candidates: List[DetectedCandidate]
    detected_at: datetime


class PlanRequest(BaseModel):
    """POST /recovery/plan - build a plan for one payment."""

    payment_id: str
    override_strategy: Optional[RecoveryStrategy] = None
    dry_run: bool = False  # don't persist the plan


class PlanResponse(BaseModel):
    plan: RecoveryPlan
    persisted: bool


class ExecuteRequest(BaseModel):
    """POST /recovery/execute - run a plan's steps through providers."""

    plan_id: Optional[str] = None
    payment_id: Optional[str] = None
    dry_run: bool = False

    @model_validator(mode="after")
    def _require_target(self) -> "ExecuteRequest":
        if not self.plan_id and not self.payment_id:
            raise ValueError("Provide either plan_id or payment_id")
        return self


class ExecuteSummary(BaseModel):
    plans_executed: int
    successes: int
    failures: int
    total_cost_paise: int
    total_recovered_paise: int
    net_value_paise: int


class ExecuteResponse(BaseModel):
    results: List[ExecutionResult]
    summary: ExecuteSummary


class RecoveryDetailResponse(BaseModel):
    recovery_id: str
    payment_id: str
    strategy: str
    status: str
    risk_score: float
    expected_amount_inr: float
    recovered_amount_inr: float
    cost_inr: float
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    last_plan: Optional[RecoveryPlan] = None
    last_result: Optional[ExecutionResult] = None
