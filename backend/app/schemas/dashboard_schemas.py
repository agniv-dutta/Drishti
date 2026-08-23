"""Request/response schemas for dashboard aggregation endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.chargeback import ChargebackRiskAssessment

DashboardStatus = Literal["failed", "recovered", "escalated"]
NodeTone = Literal["coral", "rose", "gold"]
BadgeTone = Literal["gray", "sage", "coral", "rose", "gold"]
NodePosition = Literal["above", "below"]


class DashboardPaymentItem(BaseModel):
    id: str
    amount: float
    status: DashboardStatus
    strategy_used: str
    recovered_amount: float
    last_updated: datetime
    chargeback_risk: Optional[ChargebackRiskAssessment] = None


class DashboardActivityItem(BaseModel):
    label: str
    action: str
    amount: str
    time: str
    icon: str
    payment_id: str


class DashboardJourneyNode(BaseModel):
    id: str
    title: str
    subtitle: str
    x: int
    y: NodePosition
    circle_tone: NodeTone
    completed: bool = True
    current: bool = False
    time: Optional[str] = None
    badge: Optional[str] = None
    badge_tone: Optional[BadgeTone] = None
    detail: Optional[str] = None
    preview: Optional[str] = None
    amount: Optional[str] = None
    reasoning: Optional[str] = None
    status: Optional[str] = None


class DashboardJourneyResponse(BaseModel):
    payment_id: str
    transaction_id: str
    title: str
    subtitle: str
    amount: float
    status: str
    recovered_amount: float
    nodes: List[DashboardJourneyNode] = Field(default_factory=list)
    chargeback_risk: Optional[ChargebackRiskAssessment] = None
    generated_at: datetime


class DashboardOverviewResponse(BaseModel):
    selected_payment_id: Optional[str] = None
    recovery_rate: float = 0.0
    target_rate: float = 60.0
    total_recovered: float = 0.0
    total_payments_processed: int = 0
    active_recoveries: List[DashboardPaymentItem] = Field(default_factory=list)
    activity_feed: List[DashboardActivityItem] = Field(default_factory=list)
    generated_at: datetime
