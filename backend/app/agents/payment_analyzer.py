"""Standalone payment-failure analysis agent.

This module provides the small, structured analyzer contract used by agent
integrations. It deliberately keeps optional customer/device attributes in
``PaymentTransaction.meta`` so it remains compatible with the existing
payment domain model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Mapping, Optional

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.ml.risk_scorer import get_risk_scorer
from app.models.payment import FailureReason, PaymentTransaction


class AnalysisResult(BaseModel):
    """Structured output produced for one failed payment."""

    payment_id: str
    failure_code: str
    failure_description: str
    root_causes: Dict[str, float] = Field(default_factory=dict)
    customer_segment: Literal["new", "retained", "high_value"]
    recovery_probability: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_timing: Literal["immediate", "2h", "24h", "72h"]
    reasoning: str
    next_agent: str = "StrategySelector"


class PaymentAnalyzerAgent:
    """Analyze failure cause, customer segment, and recovery likelihood."""

    def __init__(self, risk_scorer: Optional[Any] = None) -> None:
        self.risk_scorer = risk_scorer or get_risk_scorer()

    async def analyze(self, payment: PaymentTransaction) -> AnalysisResult:
        failure_code = self._failure_code(payment)
        metadata = payment.meta or {}
        customer_tenure = self._customer_tenure(payment, metadata)
        amount = payment.amount_inr
        device_type = self._metadata_value(metadata, "device_type", "unknown")
        is_weekend = payment.created_at.weekday() >= 5
        location = self._metadata_value(metadata, "location", "unknown")

        features = {
            "failure_code": failure_code,
            "amount": amount,
            "customer_tenure": customer_tenure,
            "device_type": device_type,
            "is_weekend": is_weekend,
            "location": location,
        }
        recovery_probability = self._predict_recovery(payment, features)
        segment = self._segment_customer(customer_tenure, amount, payment.attempt_number)
        timing = self._get_optimal_timing(failure_code, segment, is_weekend)
        root_causes = self._classify_root_cause(failure_code)

        return AnalysisResult(
            payment_id=payment.payment_id,
            failure_code=failure_code,
            failure_description=self._failure_description(payment, failure_code),
            root_causes=root_causes,
            customer_segment=segment,
            recovery_probability=recovery_probability,
            confidence=self._confidence(failure_code),
            recommended_timing=timing,
            reasoning=self._reasoning(failure_code, timing, recovery_probability),
        )

    def _predict_recovery(self, payment: PaymentTransaction, features: Mapping[str, Any]) -> float:
        if hasattr(self.risk_scorer, "predict"):
            prediction = self.risk_scorer.predict(dict(features))
            if hasattr(prediction, "item"):
                prediction = prediction.item()
            probability = float(prediction)
            probability = probability * 100 if probability <= 1 else probability
            return round(max(0.0, min(probability, 100.0)), 1)

        from app.ml.data_preprocessor import build_features

        score, _, _ = self.risk_scorer.score(build_features(payment))
        return round(max(0.0, min(score * 100.0, 100.0)), 1)

    @staticmethod
    def _failure_code(payment: PaymentTransaction) -> str:
        reason = payment.failure_reason
        if isinstance(reason, FailureReason):
            return reason.value
        return str(reason or payment.error_code or FailureReason.UNKNOWN.value).lower()

    @staticmethod
    def _metadata_value(metadata: Mapping[str, Any], key: str, default: str) -> str:
        value = metadata.get(key, default)
        return str(value) if value is not None else default

    @staticmethod
    def _customer_tenure(payment: PaymentTransaction, metadata: Mapping[str, Any]) -> int:
        created_at = getattr(payment.customer, "created_at", None) or metadata.get("customer_created_at")
        if not created_at:
            return 0
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - created_at).days)

    @staticmethod
    def _segment_customer(tenure: int, amount: float, attempts: int) -> Literal["new", "retained", "high_value"]:
        if amount >= get_settings().high_value_threshold_inr:
            return "high_value"
        if tenure >= 30 or attempts > 1:
            return "retained"
        return "new"

    @staticmethod
    def _classify_root_cause(failure_code: str) -> Dict[str, float]:
        if "insufficient" in failure_code:
            return {"insufficient_funds": 45.0, "declined_by_issuer": 30.0, "expired_card": 20.0}
        if "expired" in failure_code:
            return {"expired_card": 70.0, "declined_by_issuer": 20.0, "insufficient_funds": 10.0}
        if "decline" in failure_code or "bank" in failure_code:
            return {"declined_by_issuer": 70.0, "insufficient_funds": 20.0, "expired_card": 10.0}
        return {failure_code: 60.0, "declined_by_issuer": 25.0, "unknown": 15.0}

    @staticmethod
    def _get_optimal_timing(failure_code: str, segment: str, is_weekend: bool) -> Literal["immediate", "2h", "24h", "72h"]:
        if "network" in failure_code or "timeout" in failure_code:
            return "immediate"
        if "insufficient" in failure_code:
            return "72h" if is_weekend else "24h"
        if segment == "high_value":
            return "2h"
        return "24h"

    @staticmethod
    def _failure_description(payment: PaymentTransaction, failure_code: str) -> str:
        return payment.error_description or failure_code.replace("_", " ").capitalize()

    @staticmethod
    def _confidence(failure_code: str) -> float:
        return 0.78 if failure_code != FailureReason.UNKNOWN.value else 0.55

    @staticmethod
    def _reasoning(failure_code: str, timing: str, recovery_probability: float) -> str:
        return f"{failure_code.replace('_', ' ').capitalize()} pattern detected. Recovery likelihood is {recovery_probability:.1f}%; intervene {timing}."