"""Execute a selected recovery strategy through the configured providers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agents.strategy_selector import StrategyRecommendation
from app.core.logging_config import get_audit_trail
from app.integrations.crm_client import build_recovery_task, get_crm_provider
from app.integrations.email_provider import build_recovery_email, get_email_provider
from app.integrations.razorpay_client import get_razorpay_client
from app.integrations.sms_provider import build_recovery_sms, get_sms_provider
from app.integrations.voice_provider import build_hinglish_script, get_voice_provider
from app.models.payment import PaymentTransaction
from app.utils.formatters import format_inr, mask_email


class ExecutionResult(BaseModel):
    """Public result for one orchestrated recovery execution."""

    payment_id: str
    strategy: str
    status: Literal["success", "in_progress", "failed", "error", "escalated", "deferred"]
    money_recovered: float = 0.0
    execution_time: Optional[str] = None
    message: str = ""
    reason: Optional[str] = None
    error_message: Optional[str] = None
    provider_reference: Optional[str] = None
    next_step: str = "log_to_audit"
    timeout: Optional[str] = None
    execution_log: List[Dict[str, Any]] = Field(default_factory=list)
    customer_response: Optional[str] = None


class ExecutionOrchestratorAgent:
    """Execute recovery, record each provider step, and return its outcome."""

    def __init__(self, *, sms_provider=None, email_provider=None, voice_provider=None, crm=None, payment_processor=None):
        self.sms_provider = sms_provider or get_sms_provider()
        self.email_provider = email_provider or get_email_provider()
        self.voice_provider = voice_provider or get_voice_provider()
        self.crm = crm or get_crm_provider()
        self.payment_processor = payment_processor or get_razorpay_client()

    async def execute(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> ExecutionResult:
        strategy = recommendation.primary_strategy
        handlers = {
            "retry": self._execute_retry,
            "sms": self._execute_sms,
            "call": self._execute_call,
            "offer": self._execute_offer,
            "escalate": self._execute_escalate,
            "defer": self._execute_defer,
        }
        try:
            result = await handlers[strategy](payment, recommendation)
        except Exception as exc:  # provider failures become observable results
            result = ExecutionResult(
                payment_id=payment.payment_id,
                strategy=strategy,
                status="error",
                error_message=str(exc),
                message="Recovery execution failed.",
                next_step="escalate",
            )
        self._log_execution(payment, result)
        return result

    async def _execute_retry(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> ExecutionResult:
        result = await self.payment_processor.retry_payment(
            gateway_payment_id=payment.gateway_payment_id or payment.payment_id,
            amount_paise=payment.amount_paise,
            customer_name=payment.customer.name,
            customer_email=payment.customer.email,
            customer_phone=payment.customer.phone,
            reference_id=payment.payment_id,
        )
        if not result.success:
            return self._failed(payment, "retry", result.detail or "Payment retry rejected", result.reference)
        recovered = payment.amount_inr if result.raw.get("_mock") or result.raw.get("mock") else 0.0
        return ExecutionResult(
            payment_id=payment.payment_id, strategy="retry", status="success" if recovered else "in_progress",
            money_recovered=recovered, execution_time="2s", message="Retry payment link created.",
            provider_reference=result.reference, next_step="log_to_audit" if recovered else "wait_for_response",
            timeout=None if recovered else "24h",
        )

    async def _execute_sms(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> ExecutionResult:
        message = self._build_sms_message(payment, recommendation)
        result = await self.sms_provider.send(payment.customer.phone, message)
        if not result.success:
            return self._failed(payment, "sms", result.detail or "SMS delivery failed", result.reference)
        return ExecutionResult(
            payment_id=payment.payment_id, strategy="sms", status="in_progress", execution_time="0s",
            message="SMS sent to customer.", provider_reference=result.reference,
            next_step="wait_for_response", timeout="24h",
        )

    async def _execute_call(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> ExecutionResult:
        script = build_hinglish_script(payment.customer.name, format_inr(payment.amount_inr))
        result = await self.voice_provider.place_call(payment.customer.phone, script)
        if not result.success:
            return self._failed(payment, "call", result.detail or "Voice call failed", result.reference)
        return ExecutionResult(
            payment_id=payment.payment_id, strategy="call", status="in_progress", execution_time="5s",
            message="Voice recovery call initiated.", provider_reference=result.reference,
            next_step="wait_for_response", timeout="5min",
        )

    async def _execute_offer(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> ExecutionResult:
        offer_message = self._build_offer_message(payment, recommendation.max_discount_allowed)
        email = await self.email_provider.send(
            payment.customer.email,
            build_recovery_email(payment.customer.name, format_inr(payment.amount_inr), payment_link=self._retry_link(payment, True)),
        )
        sms = await self.sms_provider.send(payment.customer.phone, offer_message)
        if not email.success or not sms.success:
            detail = email.detail if not email.success else sms.detail
            return self._failed(payment, "offer", detail or "Offer delivery failed", email.reference or sms.reference)
        return ExecutionResult(
            payment_id=payment.payment_id, strategy="offer", status="in_progress",
            message="Offer sent via email and SMS.", provider_reference=email.reference or sms.reference,
            next_step="wait_for_response", timeout="48h",
        )

    async def _execute_escalate(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> ExecutionResult:
        task = build_recovery_task(
            payment_id=payment.payment_id, customer_name=payment.customer.name,
            customer_email_masked=mask_email(payment.customer.email), amount_inr=payment.amount_inr,
            failure_reason=payment.error_code or "unknown", strategy="crm_escalation", risk_score=0.0,
        )
        result = await self.crm.push_event("recovery_task_created", task)
        if not result.success:
            return self._failed(payment, "escalate", result.detail or "CRM escalation failed", result.reference)
        return ExecutionResult(
            payment_id=payment.payment_id, strategy="escalate", status="escalated",
            message="Escalated to the recovery team.", provider_reference=result.reference,
            next_step="notify_human",
        )

    async def _execute_defer(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> ExecutionResult:
        return ExecutionResult(
            payment_id=payment.payment_id, strategy="defer", status="deferred",
            message="Recovery deferred until the recommended intervention window.",
            next_step="schedule_retry", timeout="72h",
        )

    @staticmethod
    def _failed(payment: PaymentTransaction, strategy: str, reason: str, reference: Optional[str]) -> ExecutionResult:
        return ExecutionResult(
            payment_id=payment.payment_id, strategy=strategy, status="failed", reason=reason,
            message=reason, provider_reference=reference, next_step="try_next_strategy",
        )

    @staticmethod
    def _retry_link(payment: PaymentTransaction, offer: bool = False) -> str:
        return f"https://drishti.app/retry/{payment.payment_id}{'?offer=true' if offer else ''}"

    def _build_sms_message(self, payment: PaymentTransaction, recommendation: StrategyRecommendation) -> str:
        return build_recovery_sms(payment.customer.name, format_inr(payment.amount_inr), payment_link=self._retry_link(payment))

    def _build_offer_message(self, payment: PaymentTransaction, discount: float) -> str:
        return f"Complete your {format_inr(payment.amount_inr)} payment with a special discount of {format_inr(discount)}: {self._retry_link(payment, True)}"

    @staticmethod
    def _log_execution(payment: PaymentTransaction, result: ExecutionResult) -> None:
        entry = {
            "agent": "ExecutionOrchestrator", "payment_id": payment.payment_id,
            "strategy": result.strategy, "status": result.status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider_reference": result.provider_reference,
        }
        result.execution_log.append(entry)
        get_audit_trail().record(
            event_type="recovery_execution", actor="ExecutionOrchestrator",
            resource_type="payment", resource_id=payment.payment_id,
            outcome=result.status, details=entry,
        )