"""Schemas for the Verity LangGraph workflow."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class VerityRunRequest(BaseModel):
    payment_id: str
    merchant_id: str
    user_id: Optional[str] = None
    dry_run: bool = True
    thread_id: Optional[str] = None
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    contact_attempts: int = Field(default=0, ge=0)
    daily_spend_usd: float = Field(default=0.0, ge=0.0)
    resume: Optional[Dict[str, Any]] = None


class VerityRunResponse(BaseModel):
    thread_id: str
    interrupted: bool
    state: Dict[str, Any]
    interrupts: Optional[Any] = None

