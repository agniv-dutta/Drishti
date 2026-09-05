"""Voice recovery and Hinglish IVR endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import PaymentRecord, VoiceCallLog
from app.database.session import get_db
from app.i18n.messages import Language, detect_language, render_voice_script
from app.integrations.razorpay_client import get_razorpay_client
from app.integrations.voice_provider import IVRScript, get_voice_provider
from app.models.payment import utcnow
from app.utils.formatters import format_inr

router = APIRouter(
    prefix="/recovery/voice",
    tags=["voice-recovery"],
    dependencies=[Depends(require_api_key)],
)
public_router = APIRouter(prefix="/voice/webhook", tags=["voice-webhook"])

VOICE_ACTIONS = {
    "1": {"action": "retry", "message": "Customer chose to retry payment"},
    "2": {"action": "offer", "message": "Customer interested in installment"},
    "3": {"action": "defer", "message": "Customer deferred, will follow up later"},
    "4": {"action": "escalate", "message": "Customer requested human agent"},
}


class VoiceCallback(BaseModel):
    call_id: str
    payment_id: str
    pressed_key: str = Field(default="4", alias="customer_choice")
    duration_seconds: int = Field(default=0, ge=0)
    recording_url: Optional[str] = None
    call_status: str = "completed"

    model_config = {"populate_by_name": True}


def _script_for(payment: PaymentRecord, language: Language) -> tuple[IVRScript, dict[str, Any]]:
    script = render_voice_script(
        language,
        payment.customer_name,
        format_inr(payment.amount_paise / 100),
        merchant=payment.meta.get("merchant_name", "your merchant"),
    )
    if language in {Language.HINDI, Language.HINGLISH}:
        options = {
            "1": "Dobara try karein",
            "2": "Kist yojana dekhein",
            "3": "Baad mein karein",
            "4": "Human agent se baat karein",
        }
    else:
        options = {
            "1": "Retry payment",
            "2": "See installment plan",
            "3": "Defer payment",
            "4": "Speak to agent",
        }
    script.lines.extend(f"Press {key} for {label}." for key, label in options.items())
    return script, {
        "greeting": script.lines[0],
        "lines": script.lines,
        "options": options,
        "language": language.value,
    }


def _serialize_call(call: VoiceCallLog) -> dict[str, Any]:
    return {
        "call_id": call.call_id,
        "payment_id": call.payment_id,
        "language": call.language,
        "status": call.status,
        "ivr_prompt": call.script,
        "customer_choice": call.customer_choice,
        "resulting_action": call.action_taken,
        "action_message": call.action_message,
        "duration_seconds": call.duration_seconds,
        "recording_available": bool(call.recording_url and call.recording_consent),
        "recording_url": call.recording_url if call.recording_consent else None,
        "recording_consent": call.recording_consent,
        "initiated_at": call.initiated_at,
        "completed_at": call.completed_at,
    }


@router.post("/initiate-call")
async def initiate_voice_call(
    request: Request,
    payment_id: str = Query(...),
    recording_consent: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payment_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)

    try:
        customer = payment.to_domain().customer
    except Exception as exc:  # pragma: no cover - encryption configuration failure
        return error("CUSTOMER_CONTACT_UNAVAILABLE", str(exc), status_code=422, latency_ms=elapsed_ms(started), request=request)

    language = detect_language({**(payment.meta or {}), "region": (payment.meta or {}).get("region", "")})
    script, script_payload = _script_for(payment, language)
    script.record_call = recording_consent
    call_result = await get_voice_provider().place_call(customer.phone, script)
    if not call_result.success or not call_result.reference:
        return error("VOICE_CALL_FAILED", call_result.detail or "Unable to initiate voice call", status_code=502, latency_ms=elapsed_ms(started), request=request)

    call = VoiceCallLog(
        call_id=call_result.reference,
        payment_id=payment.id,
        language=language.value,
        status="initiated",
        script=script_payload,
        recording_consent=recording_consent,
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    return success({
        "call_id": call.call_id,
        "status": call.status,
        "language": call.language,
        "estimated_duration": "2-5 min",
        "callback_url": "/api/v1/voice/webhook/call-status",
        "recording_consent": call.recording_consent,
    }, agents=["VoiceRecoveryAgent"], latency_ms=elapsed_ms(started))


@router.get("/calls/{call_id}")
async def get_voice_call(call_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    started = measure()
    call = db.query(VoiceCallLog).filter(VoiceCallLog.call_id == call_id).first()
    if call is None:
        return error("VOICE_CALL_NOT_FOUND", f"voice call '{call_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    return success(_serialize_call(call), agents=["VoiceRecoveryAgent"], latency_ms=elapsed_ms(started))


async def _execute_action(action: str, payment: PaymentRecord) -> str:
    if action == "retry":
        customer = payment.to_domain().customer
        result = await get_razorpay_client().retry_payment(
            gateway_payment_id=payment.gateway_payment_id or payment.id,
            amount_paise=payment.amount_paise,
            customer_name=customer.name,
            customer_email=customer.email,
            customer_phone=customer.phone,
            reference_id=payment.id,
        )
        return "retry initiated" if result.success else f"retry failed: {result.detail}"
    if action == "offer":
        return "installment offer queued"
    if action == "defer":
        return "follow-up deferred"
    return "human agent escalation queued"


@public_router.post("/call-status")
async def handle_voice_callback(payload: VoiceCallback, db: Session = Depends(get_db)) -> dict:
    call = db.query(VoiceCallLog).filter(VoiceCallLog.call_id == payload.call_id).first()
    if call is None or call.payment_id != payload.payment_id:
        return error("VOICE_CALL_NOT_FOUND", f"voice call '{payload.call_id}' not found", status_code=404)
    payment = db.get(PaymentRecord, payload.payment_id)
    if payment is None:
        return error("PAYMENT_NOT_FOUND", f"payment '{payload.payment_id}' not found", status_code=404)

    choice = payload.pressed_key if payload.pressed_key in VOICE_ACTIONS else "4"
    selected = VOICE_ACTIONS[choice]
    action_message = await _execute_action(selected["action"], payment)
    call.customer_choice = choice
    call.action_taken = selected["action"]
    call.action_message = f"{selected['message']}; {action_message}"
    call.duration_seconds = payload.duration_seconds
    call.status = payload.call_status
    call.completed_at = utcnow()
    if call.recording_consent:
        call.recording_url = payload.recording_url
    db.commit()
    return success({"status": "processed", "action": selected["action"], "call_id": call.call_id})