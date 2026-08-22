"""Schemas for Razorpay proxy endpoints."""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, EmailStr, Field


class RefundRequest(BaseModel):
    amount_paise: Optional[int] = Field(default=None, gt=0)
    notes: Optional[Dict[str, str]] = None


class CustomerUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    contact: Optional[str] = Field(default=None, min_length=7, max_length=20)


class WebhookResponse(BaseModel):
    received: bool
    event: str
    payment_updated: bool = False
