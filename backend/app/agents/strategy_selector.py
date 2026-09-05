"""Standalone strategy selection for payment recovery."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, Field

from app.agents.payment_analyzer import AnalysisResult
from app.core.config import get_settings
from app.models.payment import PaymentTransaction

StrategyName = Literal["retry", "sms", "call", "offer", "escalate", "defer"]


class StrategyRecommendation(BaseModel):
    """Ranked recovery recommendation for a failed payment."""

    payment_id: str
    primary_strategy: StrategyName
    primary_confidence: float = Field(ge=0.0, le=1.0)
    success_probability: float = Field(ge=0.0, le=1.0)
    alternatives: List[StrategyName] = Field(min_length=2, max_length=2)
    reasoning: str
    max_discount_allowed: float = Field(ge=0.0)
    max_contact_attempts: int = Field(ge=0)
    next_agent: str = "ExecutionOrchestrator"
    gates_to_check: List[str] = Field(default_factory=list)


class StrategySelectorAgent:
    """Choose a recovery strategy from analysis, history, preferences, and rules."""

    _strategies: tuple[StrategyName, ...] = ("retry", "sms", "call", "offer", "escalate", "defer")

    async def select_strategy(
        self, payment: PaymentTransaction, analysis: AnalysisResult
    ) -> StrategyRecommendation:
        scorers = {
            "retry": self._score_retry,
            "sms": self._score_sms,
            "call": self._score_call,
            "offer": self._score_offer,
            "escalate": self._score_escalate,
            "defer": self._score_defer,
        }
        strategies = {
            name: self._apply_context(name, scorer(payment, analysis), payment)
            for name, scorer in scorers.items()
        }
        ranked = sorted(strategies.items(), key=lambda item: item[1]["success_prob"], reverse=True)
        primary_strategy, primary_score = ranked[0]

        return StrategyRecommendation(
            payment_id=payment.payment_id,
            primary_strategy=primary_strategy,
            primary_confidence=primary_score["confidence"],
            success_probability=primary_score["success_prob"],
            alternatives=[ranked[1][0], ranked[2][0]],
            reasoning=primary_score["reasoning"],
            max_discount_allowed=self._calculate_max_discount(payment, analysis),
            max_contact_attempts=self._get_contact_limit(payment),
            gates_to_check=[
                "customer_opted_out",
                "merchant_blacklisted",
                "daily_limit_exceeded",
                "confidence_threshold",
            ],
        )

    def _score_retry(self, payment: PaymentTransaction, analysis: AnalysisResult) -> Dict[str, Any]:
        code = analysis.failure_code.lower()
        if code in {"soft_decline", "network_error", "authentication_timeout"}:
            return self._score(0.85, 0.92, "Soft failure is suitable for an immediate retry.")
        return self._score(0.35, 0.60, "Retry is possible, but the failure may require customer action.")

    def _score_sms(self, payment: PaymentTransaction, analysis: AnalysisResult) -> Dict[str, Any]:
        success = 0.58 if analysis.customer_segment == "retained" else 0.42
        if self._preference(payment) == "sms":
            success += 0.10
        return self._score(min(success, 0.95), 0.70, "A customer nudge can increase the likelihood of a later retry.")

    def _score_call(self, payment: PaymentTransaction, analysis: AnalysisResult) -> Dict[str, Any]:
        if payment.amount_inr >= get_settings().high_value_threshold_inr:
            return self._score(0.72, 0.80, "High-value payment warrants a personal recovery touch.")
        success = 0.45 + (0.10 if self._preference(payment) == "call" else 0.0)
        return self._score(success, 0.65, "Voice recovery is available when digital contact is insufficient.")

    def _score_offer(self, payment: PaymentTransaction, analysis: AnalysisResult) -> Dict[str, Any]:
        if analysis.failure_code in {"risk_blocked", "card_expired", "invalid_card_details"}:
            return self._score(0.10, 0.55, "An offer cannot resolve a payment or compliance block.")
        return self._score(0.68, 0.75, "Reducing payment friction with a controlled offer may improve conversion.")

    def _score_escalate(self, payment: PaymentTransaction, analysis: AnalysisResult) -> Dict[str, Any]:
        if payment.amount_inr >= get_settings().high_value_threshold_inr or analysis.confidence < 0.60:
            return self._score(0.70, 0.82, "Human review is preferred for high-value or uncertain cases.")
        return self._score(0.22, 0.60, "Human escalation remains available but is costly for routine failures.")

    def _score_defer(self, payment: PaymentTransaction, analysis: AnalysisResult) -> Dict[str, Any]:
        if analysis.failure_code == "insufficient_funds" or analysis.recommended_timing == "72h":
            return self._score(0.64, 0.78, "Waiting gives the customer time to restore available funds.")
        return self._score(0.30, 0.58, "Deferral is a fallback when immediate recovery is unlikely.")

    @staticmethod
    def _score(success_prob: float, confidence: float, reasoning: str) -> Dict[str, Any]:
        return {
            "success_prob": max(0.0, min(success_prob, 1.0)),
            "confidence": max(0.0, min(confidence, 1.0)),
            "reasoning": reasoning,
        }

    def _apply_context(self, strategy: StrategyName, score: Dict[str, Any], payment: PaymentTransaction) -> Dict[str, Any]:
        rates = self._historical_rates(payment)
        try:
            historical = float(rates.get(strategy, 0.0)) if isinstance(rates, Mapping) else 0.0
        except (TypeError, ValueError):
            historical = 0.0
        if historical > 0:
            score["success_prob"] = round((score["success_prob"] * 0.7) + (historical * 0.3), 4)
            score["reasoning"] += " Historical success data was included."
        if strategy == "call" and self._preference(payment) == "sms":
            score["success_prob"] = max(0.0, score["success_prob"] - 0.08)
        return score

    @staticmethod
    def _historical_rates(payment: PaymentTransaction) -> Mapping[str, Any]:
        raw_rates = (payment.meta or {}).get("strategy_success_rates", {})
        if isinstance(raw_rates, Mapping):
            return raw_rates
        if isinstance(raw_rates, str):
            try:
                parsed = json.loads(raw_rates)
                return parsed if isinstance(parsed, Mapping) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _preference(payment: PaymentTransaction) -> str:
        return str((payment.meta or {}).get("communication_preference", "")).lower()

    @staticmethod
    def _calculate_max_discount(payment: PaymentTransaction, analysis: AnalysisResult) -> float:
        if analysis.failure_code in {"risk_blocked", "card_expired", "invalid_card_details"}:
            return 0.0
        return round(min(payment.amount_inr * 0.20, 5000.0), 2)

    @staticmethod
    def _get_contact_limit(payment: PaymentTransaction) -> int:
        configured = get_settings().max_recovery_attempts
        try:
            requested = int((payment.meta or {}).get("max_contact_attempts", configured))
        except (TypeError, ValueError):
            requested = configured
        return max(0, min(requested, configured))