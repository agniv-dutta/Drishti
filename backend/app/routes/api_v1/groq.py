"""LLM advisory endpoints. The advisor enriches, but does not execute, actions."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.agents.groq_advisor import GroqAdvisor
from app.core.responses import elapsed_ms, error, measure, success
from app.core.security import require_api_key
from app.database.models import PaymentRecord, RecoveryRecord
from app.database.session import get_db

router = APIRouter(prefix="/groq", tags=["groq-advisor"], dependencies=[Depends(require_api_key)])


def _payment_context(payment: PaymentRecord) -> tuple[dict, dict]:
    try:
        customer = payment.to_domain().customer.model_dump()
    except Exception:
        customer = {"name": payment.customer_name}
    return (
        {
            "payment_id": payment.id,
            "amount": round(payment.amount_paise / 100, 2),
            "currency": payment.currency,
            "failure_reason": payment.failure_reason,
            "description": (payment.meta or {}).get("description", "purchase"),
        },
        customer,
    )


def _get_payment(payment_id: str, db: Session, started: float, request: Request):
    payment = db.get(PaymentRecord, payment_id)
    if payment is None:
        return error(
            "PAYMENT_NOT_FOUND",
            f"payment '{payment_id}' not found",
            status_code=404,
            latency_ms=elapsed_ms(started),
            request=request,
        )
    return payment


@router.post("/merchant-advisor")
async def merchant_advisor(
    merchant_id: str = Query(...),
    metrics: Dict[str, Any] = Body(default_factory=dict),
):
    started = measure()
    advisor = GroqAdvisor()
    advice = await advisor.analyze_merchant_performance(merchant_id, metrics)
    return success(
        {"merchant_id": merchant_id, "advice": advice, "model": advisor.model},
        agents=["GroqAdvisor"],
        latency_ms=elapsed_ms(started),
    )


@router.post("/personalize-message")
async def personalize_message(
    request: Request,
    payment_id: str = Query(...),
    strategy: str = Query(...),
    db: Session = Depends(get_db),
):
    started = measure()
    payment = _get_payment(payment_id, db, started, request)
    if not isinstance(payment, PaymentRecord):
        return payment
    payment_data, customer = _payment_context(payment)
    message = await GroqAdvisor().generate_personalized_message(payment_data, customer, strategy)
    return success(
        {"payment_id": payment_id, "strategy": strategy, "personalized_message": message, "character_count": len(message)},
        agents=["GroqAdvisor"],
        latency_ms=elapsed_ms(started),
    )


@router.post("/compliance-check")
async def compliance_check(
    request: Request,
    payment_id: str = Query(...),
    strategy: str = Query(...),
    action: str = Query(...),
    db: Session = Depends(get_db),
):
    started = measure()
    payment = _get_payment(payment_id, db, started, request)
    if not isinstance(payment, PaymentRecord):
        return payment
    payment_data, customer = _payment_context(payment)
    result = await GroqAdvisor().check_compliance_risks(payment_data, customer, strategy, action)
    return success(result, agents=["GroqAdvisor"], latency_ms=elapsed_ms(started))


@router.post("/strategy-optimization")
async def strategy_optimization(
    request: Request,
    payment_id: str = Query(...),
    db: Session = Depends(get_db),
):
    started = measure()
    payment = _get_payment(payment_id, db, started, request)
    if not isinstance(payment, PaymentRecord):
        return payment
    payment_data, _ = _payment_context(payment)
    recoveries = db.query(RecoveryRecord).filter(RecoveryRecord.payment_id == payment_id).all()
    history = {
        "attempts": len(recoveries),
        "recovered": sum(record.recovered_amount_paise > 0 for record in recoveries),
        "strategies": [record.strategy for record in recoveries],
    }
    result = await GroqAdvisor().suggest_strategy_optimization(payment_data, history)
    return success(result, agents=["GroqAdvisor"], latency_ms=elapsed_ms(started))


@router.post("/predict-intent")
async def predict_intent(
    request: Request,
    payment_id: str = Query(...),
    db: Session = Depends(get_db),
):
    started = measure()
    payment = _get_payment(payment_id, db, started, request)
    if not isinstance(payment, PaymentRecord):
        return payment
    payment_data, customer = _payment_context(payment)
    prediction = await GroqAdvisor().predict_customer_intent(customer, payment_data)
    recommendation = "skip_contact" if prediction.get("recovery_probability", 0) > 0.75 else "contact_customer"
    return success(
        {"recommendation": recommendation, "prediction": prediction},
        agents=["GroqAdvisor"],
        latency_ms=elapsed_ms(started),
    )


@router.post("/explain-anomaly")
async def explain_anomaly(
    anomaly: str = Query(...),
    context: Dict[str, Any] = Body(default_factory=dict),
):
    started = measure()
    explanation = await GroqAdvisor().explain_anomaly(anomaly, context)
    return success(
        {"anomaly": anomaly, "explanation": explanation, "context": context},
        agents=["GroqAdvisor"],
        latency_ms=elapsed_ms(started),
    )