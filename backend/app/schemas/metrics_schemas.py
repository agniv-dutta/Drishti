"""Response schemas for /metrics endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChannelStat(BaseModel):
    channel: str
    attempts: int = 0
    successes: int = 0
    success_rate_pct: float = 0.0
    cost_inr: float = 0.0
    recovered_inr: float = 0.0


class RecoveryRateResponse(BaseModel):
    """GET /metrics/recovery-rate"""

    period_days: int
    total_attempts: int = 0
    successful_recoveries: int = 0
    failed_recoveries: int = 0
    pending_recoveries: int = 0
    recovery_rate_pct: float = 0.0
    attempted_amount_inr: float = 0.0
    recovered_amount_inr: float = 0.0
    avg_cost_per_success_inr: float = 0.0
    generated_at: datetime
    by_channel: List[ChannelStat] = Field(default_factory=list)


class CostItem(BaseModel):
    channel: str
    executions: int = 0
    total_cost_inr: float = 0.0
    avg_cost_inr: float = 0.0
    revenue_attributed_inr: float = 0.0
    roi_pct: Optional[float] = Field(
        default=None,
        description="(revenue - cost) / cost; None when cost is zero (free retries)",
    )


class CostAnalysisResponse(BaseModel):
    """GET /metrics/cost-analysis"""

    period_days: int
    total_cost_inr: float = 0.0
    total_recovered_inr: float = 0.0
    net_value_inr: float = 0.0
    roi_pct: Optional[float] = None
    items: List[CostItem] = Field(default_factory=list)
    generated_at: datetime
