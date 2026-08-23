"""Contracts for merchant-authored recovery workflows."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

WorkflowAction = Literal["retry", "wait", "sms", "email", "call", "offer", "stop", "escalate"]


class WorkflowStepPayload(BaseModel):
    type: WorkflowAction
    delay: str = "0h"
    template: Optional[str] = None
    tone: Optional[str] = None
    max_discount: Optional[str] = None

    @field_validator("delay")
    @classmethod
    def validate_delay(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized.endswith(("m", "h", "d")):
            raise ValueError("delay must end in m, h, or d")
        try:
            if int(normalized[:-1]) < 0:
                raise ValueError
        except ValueError as exc:
            raise ValueError("delay must be a non-negative duration such as 2h or 7d") from exc
        return normalized


class WorkflowCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    target_segment: str = Field(min_length=1, max_length=128)
    steps: List[WorkflowStepPayload] = Field(min_length=1, max_length=50)
    variant: Optional[str] = Field(default=None, max_length=64)


class WorkflowResponse(BaseModel):
    id: str
    name: str
    target_segment: str
    steps: List[WorkflowStepPayload]
    variant: Optional[str] = None
    success_rate: Optional[float] = None
    created_at: datetime


class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowResponse]
