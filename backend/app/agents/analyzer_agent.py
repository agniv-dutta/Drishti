"""AnalyzerAgent - classifies why a payment failed and how retryable it is.

Pipeline: gateway error-code mapping -> retryability matrix -> ML risk score
-> optional Claude enrichment for ambiguous cases. Fully functional without
an LLM key (rule engine), upgraded when one is present.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from app.agents.base_agent import BaseAgent
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.ml.data_preprocessor import build_features
from app.ml.risk_scorer import get_risk_scorer
from app.models.audit import AuditEventType, AuditSeverity
from app.models.payment import FailureReason, PaymentTransaction, Retryability
from app.models.recovery import FailureAnalysis

logger = get_logger("drishti.agent.analyzer")

# Raw gateway codes -> canonical failure reason.
GATEWAY_CODE_MAP: Dict[str, FailureReason] = {
    "insufficient_funds": FailureReason.INSUFFICIENT_FUNDS,
    "insufficient balance": FailureReason.INSUFFICIENT_FUNDS,
    "otp_timeout": FailureReason.AUTHENTICATION_TIMEOUT,
    "authentication_timeout": FailureReason.AUTHENTICATION_TIMEOUT,
    "3ds_abandoned": FailureReason.AUTHENTICATION_TIMEOUT,
    "gateway_declined": FailureReason.BANK_DECLINE,
    "do_not_honor": FailureReason.BANK_DECLINE,
    "do not honor": FailureReason.BANK_DECLINE,
    "not honored": FailureReason.BANK_DECLINE,
    "card_declined": FailureReason.BANK_DECLINE,
    "invalid_card_details": FailureReason.INVALID_CARD_DETAILS,
    "invalid cvv": FailureReason.INVALID_CARD_DETAILS,
    "invalid_cvv": FailureReason.INVALID_CARD_DETAILS,
    "card_expired": FailureReason.CARD_EXPIRED,
    "expired card": FailureReason.CARD_EXPIRED,
    "gateway_timed_out": FailureReason.NETWORK_ERROR,
    "network_error": FailureReason.NETWORK_ERROR,
    "timed out": FailureReason.NETWORK_ERROR,
    "timeout": FailureReason.NETWORK_ERROR,
    "risk_blocked": FailureReason.RISK_BLOCKED,
    "customer_abandoned": FailureReason.CUSTOMER_DROPOFF,
    # Generic fallbacks last - substring scan respects insertion order.
    "insufficient": FailureReason.INSUFFICIENT_FUNDS,
    "declined": FailureReason.BANK_DECLINE,
}

# Canonical reason -> retry posture + suggested wait before next attempt.
RETRYABILITY_BY_REASON: Dict[FailureReason, Retryability] = {
    FailureReason.INSUFFICIENT_FUNDS: Retryability.DELAYED_RETRY,
    FailureReason.AUTHENTICATION_TIMEOUT: Retryability.IMMEDIATE_RETRY,
    FailureReason.BANK_DECLINE: Retryability.DELAYED_RETRY,
    FailureReason.INVALID_CARD_DETAILS: Retryability.CUSTOMER_ACTION_REQUIRED,
    FailureReason.CARD_EXPIRED: Retryability.CUSTOMER_ACTION_REQUIRED,
    FailureReason.NETWORK_ERROR: Retryability.IMMEDIATE_RETRY,
    FailureReason.RISK_BLOCKED: Retryability.NOT_RETRYABLE,
    FailureReason.CUSTOMER_DROPOFF: Retryability.DELAYED_RETRY,
    FailureReason.UNKNOWN: Retryability.CUSTOMER_ACTION_REQUIRED,
}

WAIT_MINUTES_BY_REASON: Dict[FailureReason, int] = {
    FailureReason.INSUFFICIENT_FUNDS: 720,   # ~next day (salary credit)
    FailureReason.AUTHENTICATION_TIMEOUT: 15,
    FailureReason.BANK_DECLINE: 240,
    FailureReason.INVALID_CARD_DETAILS: 60,
    FailureReason.CARD_EXPIRED: 1440,
    FailureReason.NETWORK_ERROR: 5,
    FailureReason.RISK_BLOCKED: 0,
    FailureReason.CUSTOMER_DROPOFF: 120,
    FailureReason.UNKNOWN: 180,
}

_LLM_SYSTEM = (
    "You are a payments-failure analyst for an Indian payment gateway. "
    "Classify the failure into exactly one of these values: "
    + ", ".join(reason.value for reason in FailureReason)
    + ". Respond with ONLY a JSON object: "
    '{"root_cause": "<value>", "summary": "<one sentence>", "confidence": <0-1>}'
)


class AnalyzerAgent(BaseAgent):
    name = "analyzer"
    description = "Root-causes failed payments and scores recovery likelihood"

    async def run(self, txn: PaymentTransaction) -> FailureAnalysis:
        started = time.perf_counter()

        reason, mapping_confidence = self._resolve_reason(txn)
        retryability = RETRYABILITY_BY_REASON[reason]
        wait_minutes = WAIT_MINUTES_BY_REASON[reason]

        features = build_features(txn)
        risk_score, risk_band, contributions = get_risk_scorer().score(features)

        reasoning = self._build_reasoning(txn, reason, retryability, contributions)

        confidence = mapping_confidence
        analyzed_by = "rule-engine"
        summary = None

        # Claude enrichment only for unmapped/ambiguous failures.
        if reason == FailureReason.UNKNOWN and self.llm_enabled:
            enriched = await self._llm_classify(txn)
            if enriched:
                reason, summary, llm_confidence = enriched
                retryability = RETRYABILITY_BY_REASON[reason]
                wait_minutes = WAIT_MINUTES_BY_REASON[reason]
                reasoning.append(f"claude: {summary}")
                confidence = max(confidence, llm_confidence)
                analyzed_by = f"rule-engine+{get_settings().claude_model}"

        analysis = FailureAnalysis(
            payment_id=txn.payment_id,
            root_cause=reason,
            retryability=retryability,
            confidence=round(min(confidence, 0.99), 2),
            reasoning=reasoning,
            risk_score=risk_score,
            risk_band=risk_band,
            suggested_wait_minutes=wait_minutes,
            analyzed_by=analyzed_by,
        )

        self.audit(
            AuditEventType.PAYMENT_ANALYZED,
            resource_type="payment",
            resource_id=txn.payment_id,
            outcome=analysis.root_cause.value,
            details={
                "retryability": analysis.retryability.value,
                "risk_score": analysis.risk_score,
                "risk_band": analysis.risk_band,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "analyzed_by": analysis.analyzed_by,
            },
        )
        return analysis

    # ------------------------------------------------------------------
    def _resolve_reason(self, txn: PaymentTransaction) -> tuple[FailureReason, float]:
        """Map raw gateway code/description to a canonical FailureReason."""
        code = (txn.error_code or "").strip().lower()
        description = (txn.error_description or "").lower()

        if txn.failure_reason and txn.failure_reason != FailureReason.UNKNOWN:
            return txn.failure_reason, 0.95

        if code in GATEWAY_CODE_MAP:
            return GATEWAY_CODE_MAP[code], 0.90

        for needle, reason in GATEWAY_CODE_MAP.items():
            if needle in code or needle in description:
                return reason, 0.70

        return FailureReason.UNKNOWN, 0.40

    def _build_reasoning(
        self,
        txn: PaymentTransaction,
        reason: FailureReason,
        retryability: Retryability,
        contributions: Dict[str, float],
    ) -> List[str]:
        lines = [
            f"Gateway reported '{txn.error_code or 'n/a'}' -> classified as {reason.value}.",
            f"Retry posture: {retryability.value}.",
        ]
        for key, value in sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)[:4]:
            lines.append(f"Risk contribution {key}: {value:+.2f}")
        return lines

    async def _llm_classify(
        self, txn: PaymentTransaction
    ) -> Optional[tuple[FailureReason, str, float]]:
        prompt = (
            f"error_code: {txn.error_code or 'none'}\n"
            f"description: {txn.error_description or 'none'}\n"
            f"method: {txn.method.value}\n"
            f"amount_inr: {txn.amount_inr:.2f}\n"
            f"attempt_number: {txn.attempt_number}"
        )
        parsed = self.extract_json(self.llm_complete(_LLM_SYSTEM, prompt))
        if not parsed:
            return None
        try:
            reason = FailureReason(str(parsed["root_cause"]).strip())
        except (KeyError, ValueError):
            return None
        summary = str(parsed.get("summary", ""))[:200]
        try:
            confidence = float(parsed.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        return reason, summary, min(max(confidence, 0.3), 0.95)

    def flag_exception(self, txn: PaymentTransaction, detail: str) -> None:
        self.audit(
            AuditEventType.EXCEPTION_FLAGGED,
            resource_type="payment",
            resource_id=txn.payment_id,
            outcome="flagged",
            severity=AuditSeverity.WARNING,
            message=detail,
        )
