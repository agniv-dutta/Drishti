"""XGBoost model and encoding helpers for recovery strategy selection."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

import numpy as np
from sklearn.utils.class_weight import compute_sample_weight

from app.ml.data_preprocessor import RECOVERY_STRATEGIES

_REASONS = (
    "insufficient_funds", "authentication_timeout", "bank_decline",
    "invalid_card_details", "card_expired", "network_error",
    "risk_blocked", "customer_dropoff", "unknown",
)
_SEGMENTS = ("new", "retained", "high-value")
_PREFERENCES = ("sms", "call", "email", "none")


def strategy_feature_vector(features: Dict[str, Any]) -> List[float]:
    """One-hot encode categorical strategy features in a stable order."""
    reason = str(features.get("decline_reason", "unknown")).lower()
    segment = str(features.get("customer_segment", "new")).lower()
    preference = str(
        features.get("customer_communication_preference", "none")
    ).lower()
    return (
        [float(reason == value) for value in _REASONS]
        + [float(segment == value) for value in _SEGMENTS]
        + [float(features.get("failure_count", 0))]
        + [float(features.get("time_since_last_attempt", 0.0))]
        + [float(preference == value) for value in _PREFERENCES]
    )


def train_strategy_model(
    rows: Iterable[Dict[str, Any]],
    labels: Iterable[str],
    random_state: int = 42,
):
    """Train a class-balanced XGBoost multi-class strategy classifier."""
    from xgboost import XGBClassifier

    encoded_labels = np.array([RECOVERY_STRATEGIES.index(label) for label in labels])
    matrix = np.array([strategy_feature_vector(row) for row in rows], dtype=float)
    model = XGBClassifier(
        objective="multi:softprob",
        num_class=len(RECOVERY_STRATEGIES),
        n_estimators=120,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="mlogloss",
        random_state=random_state,
        n_jobs=1,
    )
    model.fit(
        matrix,
        encoded_labels,
        sample_weight=compute_sample_weight("balanced", encoded_labels),
    )
    return model