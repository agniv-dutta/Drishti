"""Request/response schemas for /payment endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.payment import FailureReason, PaymentMethod, PaymentStatus, Retryability
from app.utils.validators import InvalidInputError, normalize_indian_phone


class CustomerInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(description="Indian mobile; normalized to E.164 (+91XXXXXXXXXX)")

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        try:
            return normalize_indian_phone(value)
        except InvalidInputError as exc:
            raise ValueError(str(exc)) from exc


class PaymentIngestRequest(BaseModel):
    """POST /payment/ingest payload."""

    order_id: str = Field(min_length=3, max_length=64)
    gateway_payment_id: Optional[str] = Field(
        default=None, description="Razorpay payment id, e.g. pay_GAkfdm3"
    )
    customer: CustomerInput
    amount: float = Field(gt=0, le=10_000_000, description="Amount in INR (rupees)")
    currency: str = "INR"
    method: PaymentMethod
    status: PaymentStatus = PaymentStatus.FAILED
    failure_reason_code: Optional[str] = Field(
        default=None, description="Raw gateway error code, e.g. 'insufficient_funds'"
    )
    error_description: Optional[str] = None
    attempt_number: int = Field(default=1, ge=1, le=10)
    metadata: Dict[str, str] = Field(default_factory=dict)

    @property
    def amount_paise(self) -> int:
        return int(round(self.amount * 100))


class PaymentIngestResponse(BaseModel):
    payment_id: str
    order_id: str
    status: PaymentStatus
    received_at: datetime
    duplicate: bool = False
    message: str = "Payment ingested successfully"


class AnalyzeRequest(BaseModel):
    """POST /payment/analyze payload."""

    payment_id: str
    force_reanalyze: bool = False


class AnalysisOut(BaseModel):
    root_cause: FailureReason
    retryability: Retryability
    confidence: float
    reasoning: List[str]
    risk_score: float
    risk_band: str
    suggested_wait_minutes: int
    analyzed_by: str
    analyzed_at: datetime


class AnalyzeResponse(BaseModel):
    payment_id: str
    analysis: AnalysisOut
    latency_ms: float
    audit_logged: bool = True


class PaymentRecoveryRef(BaseModel):
    plan_id: str
    strategy: str
    status: str


class PaymentDetailResponse(BaseModel):
    transaction: Dict[str, Any]
    recoveries: List[PaymentRecoveryRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data):  # keep response shape tolerant
        return data
