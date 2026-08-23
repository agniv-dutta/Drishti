"""Heuristic chargeback-risk prediction for successful recoveries."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from app.models.chargeback import ChargebackRiskAssessment
from app.models.payment import PaymentMethod, PaymentTransaction
from app.models.recovery import RecoveryStrategy, StepOutcome, StepStatus

_HIGH_RISK_CATEGORIES = {
    "digital_goods",
    "digital_goods_and_services",
    "subscription",
    "subscriptions",
    "intangibles",
    "digital",
    "saas",
    "software",
}


def _meta_value(meta: dict, *keys: str, default=None):
    for key in keys:
        if key in meta and meta[key] not in (None, ""):
            return meta[key]
    return default


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _normalize_method(value) -> str:
    if isinstance(value, PaymentMethod):
        return value.value
    return str(value or "unknown").strip().lower()


def _recovery_path_label(strategy: RecoveryStrategy | str, successful_channels: Sequence[str]) -> str:
    strategy_value = strategy.value if isinstance(strategy, RecoveryStrategy) else str(strategy)
    if "voice_ivr" in successful_channels:
        return "voice_call"
    if "sms" in successful_channels:
        return "sms_recovery"
    if strategy_value == RecoveryStrategy.SMART_RETRY.value:
        return "gateway_retry"
    if strategy_value == RecoveryStrategy.CRM_HUMAN_ESCALATION.value:
        return "manual_escalation"
    return strategy_value


def _successful_channels(outcomes: Optional[Iterable[StepOutcome]]) -> List[str]:
    if not outcomes:
        return []
    channels: List[str] = []
    for outcome in outcomes:
        status = outcome.status.value if isinstance(outcome.status, StepStatus) else str(outcome.status)
        if status == StepStatus.SUCCEEDED.value:
            channels.append(outcome.channel.value)
    return channels


def _evidence_for_path(recovery_path: str) -> list[str]:
    evidence: list[str] = ["payment_receipt", "invoice_pdf"]
    if recovery_path == "sms_recovery":
        evidence.extend(["sms_delivery_proof", "email_confirmation"])
    elif recovery_path == "voice_call":
        evidence.extend(["voice_recording", "call_disposition_log"])
    elif recovery_path == "gateway_retry":
        evidence.append("gateway_retry_log")
    elif recovery_path == "manual_escalation":
        evidence.append("crm_case_notes")
    return evidence


def _risk_band(score_pct: float) -> str:
    if score_pct < 20:
        return "low"
    if score_pct < 40:
        return "medium"
    if score_pct < 70:
        return "high"
    return "critical"


def _preventive_actions(score_pct: float, evidence: list[str]) -> list[str]:
    if score_pct > 40:
        return [
            f"Store extra evidence: {', '.join(evidence)}",
            "Pre-emptively contact the customer with the invoice PDF",
            "Flag the payment for manual review by the merchant team",
        ]
    return [
        "Keep the receipt and recovery trail on file",
        "Monitor the dispute window for early warning signals",
    ]


def predict_chargeback_risk(
    txn: PaymentTransaction,
    recovery_strategy: RecoveryStrategy | str,
    outcomes: Optional[Iterable[StepOutcome]] = None,
) -> Optional[ChargebackRiskAssessment]:
    """Return a chargeback risk assessment for successful SMS/call recoveries."""

    successful_channels = _successful_channels(outcomes)
    strategy_value = recovery_strategy.value if isinstance(recovery_strategy, RecoveryStrategy) else str(recovery_strategy)
    sms_or_voice = (
        strategy_value in {
            RecoveryStrategy.NUDGE_DIGITAL.value,
            RecoveryStrategy.HIGH_TOUCH_VOICE.value,
        }
        or any(channel in {"sms", "voice_ivr"} for channel in successful_channels)
    )
    if not sms_or_voice:
        return None

    meta = txn.meta or {}
    score = 8.0
    rationale: list[str] = []
    customer_history: list[str] = []

    first_purchase = _coerce_bool(_meta_value(meta, "first_purchase", "is_first_purchase"), default=False)
    if first_purchase:
        score += 14.0
        customer_history.append("first purchase")
        rationale.append("New customers have less behavioural history to absorb dispute risk.")

    previous_chargebacks = _coerce_int(_meta_value(meta, "previous_chargebacks", "chargeback_count", "prior_chargebacks"))
    if previous_chargebacks > 0:
        score += min(32.0, 16.0 + (previous_chargebacks - 1) * 8.0)
        customer_history.append(f"{previous_chargebacks} previous chargeback(s)")
        rationale.append("Past chargebacks are one of the strongest predictors of a future dispute.")

    successful_payments = _coerce_int(
        _meta_value(meta, "successful_payments", "prior_successful_payments", "lifetime_successful_payments"),
    )
    if successful_payments >= 5:
        score -= 6.0
        customer_history.append(f"{successful_payments} prior successful payment(s)")
        rationale.append("A stable payment history reduces the likelihood of a future chargeback.")

    failed_attempts = _coerce_int(_meta_value(meta, "failed_payments", "prior_failed_payments"))
    if failed_attempts >= 2:
        score += 4.0
        customer_history.append(f"{failed_attempts} prior failed attempt(s)")
        rationale.append("Repeated payment friction can increase post-recovery dispute risk.")

    product_category = str(_meta_value(meta, "product_category", "category", "item_category", default="unknown")).strip().lower()
    if product_category in _HIGH_RISK_CATEGORIES:
        score += 18.0
        rationale.append(f"Product category '{product_category}' is typically more dispute-prone.")
    elif product_category and product_category != "unknown":
        score += 6.0
        rationale.append(f"Product category '{product_category}' carries some chargeback exposure.")

    payment_method = _normalize_method(txn.method)
    card_type = str(_meta_value(meta, "card_type", "payment_instrument", default="")).strip().lower()
    if payment_method == PaymentMethod.CARD.value:
        if card_type == "debit":
            score += 10.0
            rationale.append("Debit-card purchases can still dispute, but are slightly less risky than credit cards.")
        elif card_type == "credit":
            score += 18.0
            rationale.append("Credit-card transactions have the highest chargeback exposure.")
        else:
            score += 14.0
            rationale.append("Card payments have meaningful dispute exposure when evidence is light.")
    elif payment_method == PaymentMethod.WALLET.value:
        score += 4.0
        rationale.append("Wallet payments generally have lower chargeback exposure than card rails.")
    elif payment_method == PaymentMethod.UPI.value:
        score += 8.0
        rationale.append("UPI disputes are less common than cards but still require guardrails.")
    elif payment_method == PaymentMethod.NETBANKING.value:
        score += 6.0
        rationale.append("Netbanking disputes are lower-risk than cards but not negligible.")
    elif payment_method == PaymentMethod.EMI.value:
        score += 12.0
        rationale.append("EMI-based purchases often warrant extra documentary evidence.")

    if strategy_value == RecoveryStrategy.SMART_RETRY.value:
        score -= 6.0
        rationale.append("Silent gateway retry is the least dispute-prone recovery path.")
    elif strategy_value == RecoveryStrategy.NUDGE_DIGITAL.value:
        score += 14.0
        rationale.append("SMS-led recovery is efficient but can precede later customer friction.")
    elif strategy_value == RecoveryStrategy.HIGH_TOUCH_VOICE.value:
        score += 10.0
        rationale.append("Voice recovery creates contact but can also surface dissatisfaction early.")
    elif strategy_value == RecoveryStrategy.CRM_HUMAN_ESCALATION.value:
        score += 8.0
        rationale.append("Manual escalation is a sign that the account needs extra scrutiny.")

    if "sms" in successful_channels:
        score += 6.0
        rationale.append("The payment was recovered via SMS, which tends to correlate with later disputes.")
    if "voice_ivr" in successful_channels:
        score += 5.0
        rationale.append("A call-based recovery can indicate that the customer needed extra persuasion.")
    if "gateway_retry" in successful_channels:
        score -= 4.0
        rationale.append("A clean gateway retry is comparatively lower risk.")

    if txn.amount_inr >= 50_000:
        score += 4.0
    if txn.amount_inr >= 100_000:
        score += 4.0

    attempts = max(int(txn.attempt_number or 1), 1)
    if attempts > 1:
        score += min(6.0, (attempts - 1) * 1.5)

    score = max(0.0, min(round(score, 1), 100.0))
    band = _risk_band(score)
    evidence = _evidence_for_path(_recovery_path_label(recovery_strategy, successful_channels))
    manual_review = score > 40.0

    if manual_review:
        evidence = list(dict.fromkeys(evidence + ["sms_delivery_proof", "email_confirmation", "voice_recording"]))

    return ChargebackRiskAssessment(
        risk_score_pct=score,
        risk_band=band,
        customer_history=customer_history,
        product_category=product_category or "unknown",
        payment_method=payment_method,
        recovery_path=_recovery_path_label(recovery_strategy, successful_channels),
        evidence_to_store=list(dict.fromkeys(evidence)),
        recommended_actions=_preventive_actions(score, evidence),
        manual_review_required=manual_review,
        rationale=rationale,
    )
