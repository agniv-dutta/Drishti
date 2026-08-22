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
    method = str(raw.get("method") or "").lower()
    reason = str(raw.get("failure_reason") or "unknown").lower()

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
