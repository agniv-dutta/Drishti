"""Razorpay test-mode proxy and webhook endpoints."""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.database.models import PaymentRecord
from app.database.session import get_db
from app.integrations.razorpay_client import (
    RazorpayAuthenticationError,
    RazorpayClient,
    RazorpayError,
    RazorpayRateLimitError,
    RazorpayServerError,
    get_razorpay_client,
)
from app.schemas.razorpay_schemas import (
    CustomerUpdateRequest,
    RefundRequest,
    WebhookResponse,
)

router = APIRouter(tags=["razorpay"])
protected = [Depends(require_api_key)]


def _gateway_error(exc: RazorpayError) -> HTTPException:
    if isinstance(exc, RazorpayAuthenticationError):
        return HTTPException(status_code=502, detail="Razorpay authentication failed")
    if isinstance(exc, RazorpayRateLimitError):
        return HTTPException(status_code=429, detail="Razorpay rate limit exceeded")
    if isinstance(exc, RazorpayServerError):
        return HTTPException(status_code=502, detail="Razorpay service unavailable")
    return HTTPException(status_code=502, detail="Razorpay request failed")


@router.get("/payments/{payment_id}", dependencies=protected)
async def get_gateway_payment(
    payment_id: str,
    client: RazorpayClient = Depends(get_razorpay_client),
) -> Dict[str, Any]:
    try:
        return await client.fetch_payment(payment_id)
    except RazorpayError as exc:
        raise _gateway_error(exc) from exc


@router.post("/payments/{payment_id}/refund", dependencies=protected)
async def refund_gateway_payment(
    payment_id: str,
    payload: RefundRequest,
    client: RazorpayClient = Depends(get_razorpay_client),
) -> Dict[str, Any]:
    try:
        return await client.refund_payment(
            payment_id,
            amount_paise=payload.amount_paise,
            notes=payload.notes,
        )
    except RazorpayError as exc:
        raise _gateway_error(exc) from exc


@router.get("/customers/{customer_id}", dependencies=protected)
async def get_gateway_customer(
    customer_id: str,
    client: RazorpayClient = Depends(get_razorpay_client),
) -> Dict[str, Any]:
    try:
        return await client.fetch_customer(customer_id)
    except RazorpayError as exc:
        raise _gateway_error(exc) from exc


@router.put("/customers/{customer_id}", dependencies=protected)
async def update_gateway_customer(
    customer_id: str,
    payload: CustomerUpdateRequest,
    client: RazorpayClient = Depends(get_razorpay_client),
) -> Dict[str, Any]:
    updates = payload.model_dump(exclude_none=True, mode="json")
    if not updates:
        raise HTTPException(status_code=422, detail="At least one customer field is required")
    try:
        return await client.update_customer(customer_id, updates)
    except RazorpayError as exc:
        raise _gateway_error(exc) from exc


@router.post(
    "/webhooks",
    response_model=WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
    client: RazorpayClient = Depends(get_razorpay_client),
) -> WebhookResponse:
    body = await request.body()
    if not x_razorpay_signature or not client.verify_webhook_signature(
        body, x_razorpay_signature
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        event_body = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc

    event = str(event_body.get("event", ""))
    entity = event_body.get("payload", {}).get("payment", {}).get("entity", {})
    gateway_payment_id = entity.get("id")
    record = None
    if gateway_payment_id:
        record = (
            db.query(PaymentRecord)
            .filter(PaymentRecord.gateway_payment_id == gateway_payment_id)
            .one_or_none()
        )
        if record is not None:
            status_by_event = {
                "payment.authorized": "authorized",
                "payment.captured": "captured",
                "payment.failed": "failed",
            }
            if event in status_by_event:
                record.status = status_by_event[event]
                db.commit()

    return WebhookResponse(
        received=True,
        event=event,
        payment_updated=record is not None and event in {
            "payment.authorized", "payment.captured", "payment.failed"
        },
    )
