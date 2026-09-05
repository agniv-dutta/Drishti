"""Final compliance gate and immutable audit record for recovery decisions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agents.execution_orchestrator import ExecutionResult
from app.agents.payment_analyzer import AnalysisResult
from app.agents.strategy_selector import StrategyRecommendation
from app.core.config import get_settings
from app.core.logging_config import get_audit_trail
from app.models.payment import PaymentTransaction


class AuditResult(BaseModel):
    """Outcome of the final compliance gate."""

    payment_id: str
    approval_status: str
    gates: Dict[str, bool]
    audit_trail_id: str
    timestamp: datetime
    failed_gates: List[str] = Field(default_factory=list)
    action: str
    average_confidence: Optional[float] = None


class AuditSupervisorAgent:
    """Gate, record, and explain every recovery decision."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self.db = db

    async def gate_and_log(
        self,
        payment: PaymentTransaction,
        analysis: AnalysisResult,
        recommendation: StrategyRecommendation,
        execution: ExecutionResult,
    ) -> AuditResult:
        gates = {
            "customer_opted_out": await self._check_opted_out(payment, recommendation),
            "merchant_blacklisted": await self._check_blacklist(payment),
            "daily_limit_exceeded": await self._check_daily_limit(payment),
            "confidence_threshold": await self._check_confidence(recommendation),
            "amount_threshold": await self._check_amount_threshold(payment),
            "contact_attempt_limit": await self._check_contact_limit(payment),
            "stopping_rule_triggered": await self._check_stopping_rules(payment),
        }
        approved = all(gates.values())
        failed_gates = [name for name, passed in gates.items() if not passed]
        audit_id = uuid4().hex
        timestamp = datetime.now(timezone.utc)
        average_confidence = round((analysis.confidence + recommendation.primary_confidence) / 2, 4)
        details = {
            "audit_trail_id": audit_id,
            "payment_id": payment.payment_id,
            "status": "APPROVED" if approved else "REJECTED",
            "gates": gates,
            "failed_gates": failed_gates,
            "agent_chain": [
                ("PaymentAnalyzer", analysis.confidence),
                ("StrategySelector", recommendation.primary_confidence),
                ("ExecutionOrchestrator", 1.0),
                ("AuditSupervisor", 1.0),
            ],
            "decision_tree": {
                "failure_analysis": analysis.reasoning,
                "strategy_choice": recommendation.reasoning,
                "execution_plan": execution.message,
                "compliance_status": "COMPLIANT" if approved else "NON_COMPLIANT",
            },
            "average_confidence": average_confidence,
            "action": "PROCEED_WITH_RECOVERY" if approved else "ESCALATE_TO_HUMAN",
            "timestamp": timestamp.isoformat(),
        }
        get_audit_trail().record(
            event_type="audit_gate_decision",
            actor="AuditSupervisor",
            resource_type="payment",
            resource_id=payment.payment_id,
            outcome="APPROVED" if approved else "REJECTED",
            severity="INFO" if approved else "WARNING",
            details=details,
        )
        return AuditResult(
            payment_id=payment.payment_id,
            approval_status="APPROVED" if approved else "REJECTED",
            gates=gates,
            failed_gates=failed_gates,
            audit_trail_id=audit_id,
            timestamp=timestamp,
            action=details["action"],
            average_confidence=average_confidence,
        )

    async def _check_opted_out(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> bool:
        metadata = payment.meta or {}
        if self._as_bool(metadata.get("opted_out_recovery")):
            return False
        return not (recommendation.primary_strategy == "sms" and self._as_bool(metadata.get("opted_out_sms")))

    async def _check_blacklist(self, payment: PaymentTransaction) -> bool:
        metadata = payment.meta or {}
        merchant_id = str(metadata.get("merchant_id", ""))
        return not (
            self._as_bool(metadata.get("merchant_blacklisted"))
            or merchant_id in get_settings().blacklisted_merchant_id_set
        )

    async def _check_daily_limit(self, payment: PaymentTransaction) -> bool:
        metadata = payment.meta or {}
        if self._as_bool(metadata.get("daily_limit_exceeded")):
            return False
        count = await self._count("count_recoveries_today", payment.payment_id)
        limit = self._as_int(metadata.get("daily_recovery_limit"), 1000)
        return count < limit

    async def _check_confidence(self, recommendation: StrategyRecommendation) -> bool:
        return recommendation.primary_confidence >= get_settings().ask_customer_confidence

    async def _check_amount_threshold(self, payment: PaymentTransaction) -> bool:
        return payment.amount_inr <= get_settings().triage_high_value_inr

    async def _check_contact_limit(self, payment: PaymentTransaction) -> bool:
        count = await self._count("count_contact_attempts", payment.payment_id, last_days=7)
        configured = self._as_int((payment.meta or {}).get("max_contact_attempts"), 3)
        return count < min(configured, 3)

    async def _check_stopping_rules(self, payment: PaymentTransaction) -> bool:
        metadata = payment.meta or {}
        if self._as_bool(metadata.get("customer_complained")):
            return False
        now = datetime.now(timezone.utc)
        if now.hour >= 21 or now.weekday() >= 5:
            return False
        complaint = metadata.get("last_complaint_date")
        if complaint:
            try:
                when = datetime.fromisoformat(str(complaint).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return when <= now - timedelta(days=7)
            except ValueError:
                return False
        return True

    async def _count(self, method_name: str, *args: Any, **kwargs: Any) -> int:
        if self.db is None or not hasattr(self.db, method_name):
            return 0
        result = getattr(self.db, method_name)(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
        return int(result or 0)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        return str(value).lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default