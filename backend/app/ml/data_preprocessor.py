"""Feature engineering shared by scoring, classification and drift checks."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List

FEATURE_NAMES: List[str] = [
    "amount_log",
    "attempt_number",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    # method one-hots
    "method_card",
    "method_netbanking",
    "method_upi",
    "method_wallet",
    "method_emi",
    # failure reason one-hots
    "reason_insufficient_funds",
    "reason_authentication_timeout",
    "reason_bank_decline",
    "reason_invalid_card_details",
    "reason_card_expired",
    "reason_network_error",
    "reason_risk_blocked",
    "reason_customer_dropoff",
    "reason_unknown",
]

STRATEGY_FEATURE_NAMES: List[str] = [
    "decline_reason",
    "customer_segment",
    "failure_count",
    "time_since_last_attempt",
    "customer_communication_preference",
]

RECOVERY_STRATEGIES: List[str] = ["retry", "sms", "call", "offer", "escalate"]


def build_strategy_features(
    decline_reason: str,
    customer_segment: str,
    failure_count: int,
    time_since_last_attempt: float,
    customer_communication_preference: str,
) -> Dict[str, Any]:
    """Return the raw feature record used by the strategy classifier."""
    if failure_count < 0:
        raise ValueError("failure_count must be non-negative")
    if time_since_last_attempt < 0:
        raise ValueError("time_since_last_attempt must be non-negative")
    return {
        "decline_reason": str(decline_reason).lower(),
        "customer_segment": str(customer_segment).lower(),
        "failure_count": int(failure_count),
        "time_since_last_attempt": float(time_since_last_attempt),
        "customer_communication_preference": str(
            customer_communication_preference
        ).lower(),
    }


def _as_dict(txn_or_dict: Any) -> Dict[str, Any]:
    if isinstance(txn_or_dict, dict):
        return txn_or_dict
    return txn_or_dict.model_dump(mode="python")


def build_features(txn_or_dict: Any) -> Dict[str, float]:
    """Build the canonical feature vector from a PaymentTransaction (or its dict)."""
    raw = _as_dict(txn_or_dict)

    amount_paise = int(raw.get("amount_paise") or 0)
    amount_inr = amount_paise / 100.0 if amount_paise else float(raw.get("amount", 0) or 0)

    created_at: datetime = raw.get("created_at") or datetime.utcnow()
    method = str(getattr(raw.get("method"), "value", raw.get("method")) or "").lower()
    # Tolerate enums ("FailureReason.X" -> "x"), plain strings, and None.
    reason_value = getattr(raw.get("failure_reason"), "value", raw.get("failure_reason"))
    reason = str(reason_value or "unknown").lower().split(".")[-1]

    features: Dict[str, float] = {
        "amount_log": math.log1p(max(amount_inr, 0.0)),
        "attempt_number": float(int(raw.get("attempt_number") or 1)),
        "hour_of_day": float(created_at.hour),
        "day_of_week": float(created_at.weekday()),
        "is_weekend": 1.0 if created_at.weekday() >= 5 else 0.0,
    }
    for name in ("card", "netbanking", "upi", "wallet", "emi"):
        features[f"method_{name}"] = 1.0 if method == name else 0.0
    for reason_enum in [
        "insufficient_funds", "authentication_timeout", "bank_decline",
        "invalid_card_details", "card_expired", "network_error",
        "risk_blocked", "customer_dropoff", "unknown",
    ]:
        features[f"reason_{reason_enum}"] = 1.0 if reason == reason_enum else 0.0

    return {name: features.get(name, 0.0) for name in FEATURE_NAMES}


def to_vector(features: Dict[str, float]) -> List[float]:
    """Ordered vector matching FEATURE_NAMES - input shape for sklearn models."""
    return [float(features[name]) for name in FEATURE_NAMES]
