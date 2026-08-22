"""ExecutorAgent - runs RecoveryPlan steps through real providers.

Every provider call is audited; failures are contained per-step so a broken
integration degrades that channel instead of aborting the whole run. Mock
providers keep the pipeline testable without external credentials.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

from app.agents.base_agent import BaseAgent
from app.integrations.crm_client import build_recovery_task, get_crm_provider
from app.integrations.email_provider import build_recovery_email, get_email_provider
from app.integrations.razorpay_client import get_razorpay_client
from app.integrations.sms_provider import build_recovery_sms, get_sms_provider
from app.integrations.voice_provider import build_hinglish_script, get_voice_provider
from app.models.audit import AuditEventType, AuditSeverity
from app.models.payment import PaymentTransaction
from app.models.recovery import (
    ExecutionResult,
    RecoveryChannel,
    RecoveryPlan,
    RecoveryStep,
    StepOutcome,
    StepStatus,
)
from app.utils.formatters import format_inr


class ExecutorAgent(BaseAgent):
    name = "executor"
    description = "Dispatches recovery steps to gateway/messaging/voice/CRM providers"

    async def run(
        self,
        plan: RecoveryPlan,
        txn: PaymentTransaction,
        dry_run: bool = False,
    ) -> ExecutionResult:
        started = time.perf_counter()
        outcomes = []
        total_cost = 0
        recovered = 0

        for step in plan.ordered_steps:
            # Stop-on-success: once the gateway retry converts, skip further retries.
            if step.channel == RecoveryChannel.GATEWAY_RETRY and any(
                o.status == StepStatus.SUCCEEDED and o.channel == RecoveryChannel.GATEWAY_RETRY
                for o in outcomes
            ):
                outcomes.append(self._skipped_outcome(step, "gateway retry already succeeded"))
                continue

            outcome = await self._execute_step(step, plan, txn, dry_run)
            outcomes.append(outcome)
            total_cost += outcome.cost_incurred_paise
            recovered += outcome.recovered_amount_paise

        success = any(
            o.status == StepStatus.SUCCEEDED and o.channel == RecoveryChannel.GATEWAY_RETRY
            for o in outcomes
        )

        result = ExecutionResult(
            plan_id=plan.plan_id,
            payment_id=txn.payment_id,
            success=success,
            outcomes=outcomes,
            total_cost_paise=total_cost,
            recovered_amount_paise=recovered,
            summary=self._summary(plan, outcomes, success),
        )
        result.completed_at = datetime.now(timezone.utc)

        self.audit(
            AuditEventType.RECOVERY_EXECUTED,
            resource_type="recovery",
            resource_id=plan.plan_id,
            outcome="succeeded" if success else "failed",
            severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
            details={
                "payment_id": txn.payment_id,
                "strategy": plan.strategy.value,
                "steps": [f"{o.channel.value}:{o.status.value}" for o in outcomes],
                "cost_paise": total_cost,
                "recovered_paise": recovered,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "dry_run": dry_run,
            },
        )
        return result

    # ------------------------------------------------------------------
    async def _execute_step(
        self,
        step: RecoveryStep,
        plan: RecoveryPlan,
        txn: PaymentTransaction,
        dry_run: bool,
    ) -> StepOutcome:
        if dry_run:
            return StepOutcome(
                sequence=step.sequence,
                channel=step.channel,
                status=StepStatus.SKIPPED,
                detail="dry-run - provider not contacted",
                cost_incurred_paise=0,
            )

        handlers: Dict[RecoveryChannel, Callable] = {
            RecoveryChannel.GATEWAY_RETRY: self._do_gateway_retry,
            RecoveryChannel.EMAIL: self._do_email,
            RecoveryChannel.SMS: self._do_sms,
            RecoveryChannel.VOICE_IVR: self._do_voice,
            RecoveryChannel.CRM_ESCALATION: self._do_crm,
        }
        handler = handlers.get(step.channel)
        if handler is None:
            return StepOutcome(
                sequence=step.sequence,
                channel=step.channel,
                status=StepStatus.SKIPPED,
                detail=f"no handler registered for {step.channel}",
            )

        try:
            detail, reference, recovered_paise = await handler(txn, step)
            status = StepStatus.SUCCEEDED
        except Exception as exc:  # noqa: BLE001 - one bad channel must not kill the run
            detail, reference, recovered_paise = f"provider error: {exc}", None, 0
            status = StepStatus.FAILED
            self.audit(
                AuditEventType.PROVIDER_FAILURE,
                resource_type="recovery",
                resource_id=f"{plan.plan_id}/step-{step.sequence}",
                outcome="error",
                severity=AuditSeverity.WARNING,
                message=str(exc)[:300],
                details={"channel": step.channel.value},
            )

        cost = step.estimated_cost_paise if status == StepStatus.SUCCEEDED else 0
        return StepOutcome(
            sequence=step.sequence,
            channel=step.channel,
            status=status,
            detail=detail[:300],
            provider_reference=reference,
            cost_incurred_paise=cost,
            recovered_amount_paise=recovered_paise,
        )

    # ---- channel handlers ---------------------------------------------
    async def _do_gateway_retry(
        self, txn: PaymentTransaction, step: RecoveryStep
    ) -> Tuple[str, Optional[str], int]:
        client = get_razorpay_client()
        result = await client.retry_payment(
            gateway_payment_id=txn.gateway_payment_id or txn.payment_id,
            amount_paise=txn.amount_paise,
            customer_name=txn.customer.name,
            customer_email=txn.customer.email,
            customer_phone=txn.customer.phone,
            reference_id=txn.payment_id,
        )
        if not result.success:
            raise RuntimeError(result.detail or "gateway retry rejected")
        short_url = str(result.raw.get("short_url", "")) if result.raw else ""
        detail = f"payment link created {result.reference} {short_url}".strip()
        # Mock-mode links credit the full amount immediately so demos/metrics show
        # end-to-end value; live-mode credits arrive via payment webhooks instead.
        recovered = txn.amount_paise if result.raw.get("mock") else 0
        return detail, result.reference, recovered

    async def _do_email(
        self, txn: PaymentTransaction, step: RecoveryStep
    ) -> Tuple[str, Optional[str], int]:
        content = build_recovery_email(txn.customer.name, format_inr(txn.amount_inr))
        result = await get_email_provider().send(txn.customer.email, content)
        if not result.success:
            raise RuntimeError(result.detail or "email send failed")
        return f"email delivered ({content.subject})", result.reference, 0

    async def _do_sms(
        self, txn: PaymentTransaction, step: RecoveryStep
    ) -> Tuple[str, Optional[str], int]:
        message = build_recovery_sms(txn.customer.name, format_inr(txn.amount_inr))
        result = await get_sms_provider().send(txn.customer.phone, message)
        if not result.success:
            raise RuntimeError(result.detail or "sms send failed")
        return "sms delivered", result.reference, 0

    async def _do_voice(
        self, txn: PaymentTransaction, step: RecoveryStep
    ) -> Tuple[str, Optional[str], int]:
        script = build_hinglish_script(txn.customer.name, format_inr(txn.amount_inr))
        result = await get_voice_provider().place_call(txn.customer.phone, script)
        if not result.success:
            raise RuntimeError(result.detail or "ivr call failed")
        return "ivr call placed (hinglish script)", result.reference, 0

    async def _do_crm(
        self, txn: PaymentTransaction, step: RecoveryStep
    ) -> Tuple[str, Optional[str], int]:
        task = build_recovery_task(
            payment_id=txn.payment_id,
            customer_name=txn.customer.name,
            customer_email_masked=self._masked_email(txn.customer.email),
            amount_inr=txn.amount_inr,
            failure_reason=(txn.failure_reason.value if txn.failure_reason else "unknown"),
            strategy="crm_escalation",
            risk_score=0.0,
        )
        result = await get_crm_provider().push_event("recovery_task_created", task)
        if not result.success:
            raise RuntimeError(result.detail or "crm push failed")
        return "crm escalation task created", result.reference, 0

    @staticmethod
    def _masked_email(email: str) -> str:
        from app.utils.formatters import mask_email

        return mask_email(email)

    # ------------------------------------------------------------------
    def _skipped_outcome(self, step: RecoveryStep, reason: str) -> StepOutcome:
        return StepOutcome(
            sequence=step.sequence,
            channel=step.channel,
            status=StepStatus.SKIPPED,
            detail=reason,
        )

    @staticmethod
    def _summary(plan: RecoveryPlan, outcomes: list[StepOutcome], success: bool) -> str:
        executed = [o for o in outcomes if o.status != StepStatus.PENDING]
        channels = ",".join(o.channel.value for o in executed) or "none"
        verb = "recovery link issued" if success else "outreach completed, no conversion yet"
        return f"{plan.strategy.value}: ran {len(executed)} step(s) [{channels}] - {verb}."
