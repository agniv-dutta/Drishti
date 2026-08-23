"""Confidence-based routing between automation and human judgment.

Decision tree (configurable thresholds):
    confidence > 0.85          -> execute automatically
    0.70 < confidence <= 0.85  -> execute but monitor (flag on failure)
    0.50 < confidence <= 0.70  -> ask the customer "Would you like help?"
    confidence <= 0.50         -> escalate to a human immediately

Low-confidence payments land in a priority-ordered triage queue where agents
can override the strategy, edit the outbound message, and close the loop in
the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.models.payment import PaymentTransaction
from app.models.recovery import RecoveryPlan


logger = get_logger("drishti.routing")


class RoutingAction(str, Enum):
    AUTO_EXECUTE = "auto_execute"
    EXECUTE_MONITOR = "execute_monitor"
    ASK_CUSTOMER = "ask_customer"
    HUMAN_ESCALATION = "human_escalation"


CONSENT_QUESTION = "Would you like help completing your payment? Reply YES or NO."


@dataclass
class RoutingDecision:
    action: RoutingAction
    confidence: float
    reasons: List[str] = field(default_factory=list)
    priority_score: float = 0.0
    monitor: bool = False
    question: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
            "priority_score": round(self.priority_score, 2),
            "monitor": self.monitor,
            "question": self.question,
        }


def classify_confidence(confidence: float) -> RoutingAction:
    settings = get_settings()
    if confidence > settings.auto_execute_confidence:
        return RoutingAction.AUTO_EXECUTE
    if confidence > settings.monitor_confidence:
        return RoutingAction.EXECUTE_MONITOR
    if confidence > settings.ask_customer_confidence:
        return RoutingAction.ASK_CUSTOMER
    return RoutingAction.HUMAN_ESCALATION


def low_confidence_reasons(
    txn: PaymentTransaction,
    plan: RecoveryPlan,
) -> List[str]:
    """Explain *why* the model is unsure - shown to triage agents."""
    settings = get_settings()
    reasons: List[str] = []

    if txn.amount_inr >= settings.triage_high_value_inr:
        reasons.append(f"high_value_payment (₹{txn.amount_inr:,.0f})")

    reason_value = txn.failure_reason.value if txn.failure_reason else None
    if reason_value is None:
        reasons.append("ambiguous_failure (no failure reason from gateway)")
    elif reason_value in {"unknown", "other"}:
        reasons.append(f"ambiguous_failure ({reason_value})")

    description = (txn.error_description or "").lower()
    if any(marker in description for marker in ("unknown", "ambiguous", "timeout", "try again")):
        reasons.append("vague_gateway_error_description")

    history = txn.meta.get("past_payments")
    if not history:
        reasons.append("new_customer_no_history")

    if plan.strategy.value == "write_off":
        reasons.append("write_off_recommended_needs_confirmation")

    return reasons


def priority_score(txn: PaymentTransaction, has_history: bool) -> float:
    """Queue ordering: high-value first, new customers second.

    Score range roughly 0-105: amount dominates (10 pts per lakh capped at
    100), new customers get a +5 nudge so they surface before stale low-value
    items at similar amounts.
    """
    amount_component = min(txn.amount_inr / 100_000.0, 10.0) * 10.0
    new_customer_bonus = 0.0 if has_history else 5.0
    return amount_component + new_customer_bonus


class ConfidenceRouter:
    """Stateless decision maker; supervisor persists the outcome."""

    name = "confidence_router"

    def route(self, txn: PaymentTransaction, plan: RecoveryPlan) -> RoutingDecision:
        confidence = float(plan.expected_success_probability)
        action = classify_confidence(confidence)
        reasons = low_confidence_reasons(txn, plan)
        has_history = bool(txn.meta.get("past_payments"))

        decision = RoutingDecision(
            action=action,
            confidence=confidence,
            reasons=reasons,
            priority_score=priority_score(txn, has_history),
            monitor=action is RoutingAction.EXECUTE_MONITOR,
            question=CONSENT_QUESTION if action is RoutingAction.ASK_CUSTOMER else None,
        )
        logger.info(
            "routing.decided",
            payment_id=txn.payment_id,
            action=decision.action.value,
            confidence=round(confidence, 3),
            priority=round(decision.priority_score, 1),
        )
        return decision


_router: Optional[ConfidenceRouter] = None


def get_confidence_router() -> ConfidenceRouter:
    global _router
    if _router is None:
        _router = ConfidenceRouter()
    return _router
