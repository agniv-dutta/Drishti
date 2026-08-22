"""LangGraph-based multi-agent workflow for Verity."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, TypedDict

from fastapi import WebSocket
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.analyzer_agent import AnalyzerAgent
from app.agents.base_agent import BaseAgent
from app.agents.prompts import (
    AUDIT_SUPERVISOR_SYSTEM_PROMPT,
    EXECUTION_ORCHESTRATOR_SYSTEM_PROMPT,
    PAYMENT_ANALYZER_SYSTEM_PROMPT,
    STRATEGY_SELECTOR_SYSTEM_PROMPT,
)
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.database.models import AuditLog, PaymentRecord
from app.models.payment import PaymentTransaction, utcnow
from app.models.recovery import FailureAnalysis
from app.integrations.email_provider import build_recovery_email, get_email_provider
from app.integrations.sms_provider import build_recovery_sms, get_sms_provider
from app.integrations.voice_provider import build_hinglish_script, get_voice_provider
from app.utils.formatters import format_inr, mask_email

logger = get_logger("drishti.verity")

AsyncEmitter = Callable[[Dict[str, Any]], Awaitable[None]]


class FailureLikelihood(BaseModel):
    label: str
    probability: float = Field(ge=0.0, le=100.0)


class PaymentAnalysisOutput(BaseModel):
    primary_failure_reason: Dict[str, str]
    customer_segment: Literal["new", "retained", "high-value"]
    root_cause_likelihood: List[FailureLikelihood] = Field(default_factory=list)
    recovery_probability: float = Field(ge=0.0, le=100.0)
    recommended_intervention_timing: Literal["immediate", "24h", "72h"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = ""


class StrategyDecision(BaseModel):
    strategy: Literal["RETRY", "SMS", "CALL", "OFFER", "ESCALATE", "DEFER"]
    confidence: float = Field(ge=0.0, le=100.0)
    stopping_condition: str
    rationale: str = ""


class WorkflowStep(BaseModel):
    step: int
    action: Literal["SMS", "EMAIL", "VOICE", "RETRY", "WAIT", "CRM"]
    wait_hours: int = 0
    status: Literal["pending", "scheduled", "sent", "failed", "skipped"] = "pending"
    detail: str = ""


class ExecutionOutcome(BaseModel):
    channel_used: str
    timestamp: datetime = Field(default_factory=utcnow)
    customer_response: Optional[str] = None
    money_recovered: float = 0.0
    workflow: List[WorkflowStep] = Field(default_factory=list)
    summary: str = ""


class AuditDecision(BaseModel):
    approved: bool
    reason: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    violations: List[str] = Field(default_factory=list)


class VerityState(TypedDict, total=False):
    payment_id: str
    merchant_id: str
    user_id: str
    dry_run: bool
    confidence_threshold: float
    payment: Dict[str, Any]
    analysis: Dict[str, Any]
    strategy: Dict[str, Any]
    execution: Dict[str, Any]
    audit: Dict[str, Any]
    trace: List[Dict[str, Any]]
    stop_reason: str
    contact_attempts: int
    daily_spend_usd: float
    recovery_amount_usd: float
    approved: bool


def _append_trace(state: VerityState, stage: str, summary: str, **extra: Any) -> Dict[str, Any]:
    trace = list(state.get("trace", []))
    entry = {
        "stage": stage,
        "summary": summary,
        "timestamp": utcnow().isoformat(),
        **extra,
    }
    trace.append(entry)
    return {"trace": trace}


def _customer_segment(amount_paise: int, attempt_number: int) -> str:
    settings = get_settings()
    amount_inr = amount_paise / 100.0
    if amount_inr >= settings.high_value_threshold_inr:
        return "high-value"
    if attempt_number > 1:
        return "retained"
    return "new"


def _root_cause_likelihood(root_cause: str) -> List[FailureLikelihood]:
    base = {
        "declined by bank": 25.0,
        "insufficient funds": 25.0,
        "timeout": 15.0,
        "customer dropoff": 10.0,
        "risk blocked": 10.0,
    }
    if "insufficient" in root_cause:
        base["insufficient funds"] = 50.0
        base["declined by bank"] = 20.0
    elif "decline" in root_cause or "bank" in root_cause:
        base["declined by bank"] = 55.0
        base["insufficient funds"] = 20.0
    elif "timeout" in root_cause:
        base["timeout"] = 60.0
    total = sum(base.values()) or 1.0
    return [FailureLikelihood(label=k, probability=round(v * 100.0 / total, 1)) for k, v in base.items()]


def _intervention_timing(wait_minutes: int) -> str:
    if wait_minutes <= 30:
        return "immediate"
    if wait_minutes <= 24 * 60:
        return "24h"
    return "72h"


def _strategy_for_analysis(analysis: PaymentAnalysisOutput, txn: PaymentTransaction) -> StrategyDecision:
    reason = analysis.primary_failure_reason["code"]
    amount_inr = txn.amount_inr
    if analysis.customer_segment == "high-value":
        strategy = "ESCALATE"
        stopping = "Escalate to human if the account is high-value or if customer objections appear."
        conf = 82.0
        rationale = "High-value account; human oversight is preferred."
    elif "insufficient" in reason:
        strategy = "DEFER"
        stopping = "Wait 72h, then retry once if the payment is still open."
        conf = 74.0
        rationale = "Insufficient funds often improves after a delay."
    elif "timeout" in reason or "network" in reason:
        strategy = "RETRY"
        stopping = "Stop after 3 retries or on customer opt-out."
        conf = 86.0
        rationale = "Soft failure with high retryability."
    elif amount_inr <= 1000:
        strategy = "SMS"
        stopping = "Stop after 3 contact attempts or customer opt-out."
        conf = 78.0
        rationale = "Low-value payment; SMS is efficient."
    else:
        strategy = "CALL"
        stopping = "Stop after 3 contact attempts, or if the customer objects."
        conf = 70.0
        rationale = "Voice outreach offers a higher-touch recovery path."
    if analysis.recovery_probability >= 80:
        strategy = "SMS" if strategy != "ESCALATE" else strategy
    return StrategyDecision(strategy=strategy, confidence=conf, stopping_condition=stopping, rationale=rationale)


class VerityPaymentAnalyzer(BaseAgent):
    name = "payment_analyzer"
    description = "Analyzes payment failure reasons and recovery likelihood"
    system_prompt = PAYMENT_ANALYZER_SYSTEM_PROMPT

    async def analyze(self, txn: PaymentTransaction) -> PaymentAnalysisOutput:
        prompt = (
            f"transaction_id: {txn.payment_id}\n"
            f"order_id: {txn.order_id}\n"
            f"error_code: {txn.error_code or 'none'}\n"
            f"error_description: {txn.error_description or 'none'}\n"
            f"amount_inr: {txn.amount_inr:.2f}\n"
            f"attempt_number: {txn.attempt_number}\n"
            f"currency: {txn.currency}\n"
            f"customer_name: {txn.customer.name}\n"
            f"customer_email: {txn.customer.email}\n"
        )
        parsed = self.extract_json(self.llm_complete(self.system_prompt, prompt))
        if parsed:
            try:
                primary = parsed.get("primary_failure_reason") or {}
                confidence = float(parsed.get("confidence", 0.55))
                recovery_probability = float(parsed.get("recovery_probability", 35))
                timing = str(parsed.get("recommended_intervention_timing", "24h"))
                segment = str(parsed.get("customer_segment", _customer_segment(txn.amount_paise, txn.attempt_number)))
                if timing not in {"immediate", "24h", "72h"}:
                    timing = _intervention_timing(24 * 60)
                root = parsed.get("root_cause_likelihood") or []
                likelihoods = [
                    FailureLikelihood(
                        label=str(item.get("label", item.get("reason", "unknown"))),
                        probability=float(item.get("probability", 0.0)),
                    )
                    for item in root
                    if isinstance(item, dict)
                ]
                if likelihoods:
                    return PaymentAnalysisOutput(
                        primary_failure_reason={
                            "code": str(primary.get("code", primary.get("reason", "unknown"))),
                            "description": str(primary.get("description", primary.get("code", "unknown"))),
                        },
                        customer_segment=segment,  # type: ignore[arg-type]
                        root_cause_likelihood=likelihoods,
                        recovery_probability=max(0.0, min(recovery_probability, 100.0)),
                        recommended_intervention_timing=timing,  # type: ignore[arg-type]
                        confidence=max(0.0, min(confidence, 1.0)),
                        reasoning_summary=str(parsed.get("reasoning_summary", parsed.get("summary", "")))[:500],
                    )
            except Exception:
                logger.debug("verity.analyzer.llm_parse_failed", exc_info=True)

        legacy = AnalyzerAgent()
        legacy.bind_db(self.db)
        failure: FailureAnalysis = await legacy.run(txn)
        return PaymentAnalysisOutput(
            primary_failure_reason={
                "code": failure.root_cause.value,
                "description": txn.error_description or txn.error_code or failure.root_cause.value,
            },
            customer_segment=_customer_segment(txn.amount_paise, txn.attempt_number),  # type: ignore[arg-type]
            root_cause_likelihood=_root_cause_likelihood(failure.root_cause.value),
            recovery_probability=round(failure.risk_score * 100.0, 1),
            recommended_intervention_timing=_intervention_timing(failure.suggested_wait_minutes),
            confidence=failure.confidence,
            reasoning_summary="; ".join(failure.reasoning[:3]),
        )


class VerityStrategySelector(BaseAgent):
    name = "strategy_selector"
    description = "Chooses a recovery path from the payment analysis"
    system_prompt = STRATEGY_SELECTOR_SYSTEM_PROMPT

    async def select(self, analysis: PaymentAnalysisOutput, txn: PaymentTransaction) -> StrategyDecision:
        prompt = (
            f"analysis_json: {analysis.model_dump_json()}\n"
            f"amount_inr: {txn.amount_inr:.2f}\n"
            f"attempt_number: {txn.attempt_number}\n"
            f"customer_email: {mask_email(txn.customer.email)}\n"
            f"customer_phone: {txn.customer.phone}\n"
        )
        parsed = self.extract_json(self.llm_complete(self.system_prompt, prompt))
        if parsed:
            try:
                strategy = str(parsed["strategy"]).strip().upper()
                confidence = float(parsed.get("confidence", 70.0))
                stopping = str(parsed.get("stopping_condition", "")).strip()
                if strategy in {"RETRY", "SMS", "CALL", "OFFER", "ESCALATE", "DEFER"}:
                    return StrategyDecision(
                        strategy=strategy,  # type: ignore[arg-type]
                        confidence=max(0.0, min(confidence, 100.0)),
                        stopping_condition=stopping or "Stop on customer opt-out or hard limit",
                        rationale=str(parsed.get("rationale", ""))[:500],
                    )
            except Exception:
                logger.debug("verity.strategy.llm_parse_failed", exc_info=True)
        return _strategy_for_analysis(analysis, txn)


class VerityExecutionOrchestrator(BaseAgent):
    name = "execution_orchestrator"
    description = "Runs the recovery workflow"
    system_prompt = EXECUTION_ORCHESTRATOR_SYSTEM_PROMPT

    async def execute(
        self,
        txn: PaymentTransaction,
        analysis: PaymentAnalysisOutput,
        strategy: StrategyDecision,
        *,
        dry_run: bool = True,
        audit_gate: Optional[Callable[[str, float], Awaitable[AuditDecision]]] = None,
    ) -> ExecutionOutcome:
        workflow = self._build_workflow(strategy, txn)
        channel_used = "none"
        recovered = 0.0
        response: Optional[str] = None

        for step in workflow:
            if step.action == "WAIT":
                step.status = "scheduled"
                continue

            if audit_gate is not None:
                decision = await audit_gate(step.action, recovered)
                if not decision.approved:
                    step.status = "skipped"
                    step.detail = decision.reason
                    return ExecutionOutcome(
                        channel_used=channel_used,
                        customer_response=response,
                        money_recovered=recovered,
                        workflow=workflow,
                        summary=f"stopped: {decision.reason}",
                    )

            if dry_run:
                step.status = "scheduled" if step.wait_hours else "pending"
                step.detail = "dry-run"
                channel_used = step.action.lower()
                continue

            try:
                detail = await self._perform_action(txn, step)
                step.status = "sent"
                step.detail = detail
                channel_used = step.action.lower()
                if step.action == "RETRY":
                    recovered = txn.amount_inr
                    response = "payment retried"
            except Exception as exc:  # noqa: BLE001
                step.status = "failed"
                step.detail = str(exc)[:200]

        summary = (
            f"{strategy.strategy}: {channel_used} executed; "
            f"{'no live provider calls (dry-run)' if dry_run else 'workflow completed'}."
        )
        return ExecutionOutcome(
            channel_used=channel_used,
            customer_response=response,
            money_recovered=recovered,
            workflow=workflow,
            summary=summary,
        )

    def _build_workflow(self, strategy: StrategyDecision, txn: PaymentTransaction) -> List[WorkflowStep]:
        if strategy.strategy == "RETRY":
            return [
                WorkflowStep(step=1, action="RETRY", wait_hours=0),
                WorkflowStep(step=2, action="WAIT", wait_hours=24, status="scheduled", detail="wait 24h"),
                WorkflowStep(step=3, action="EMAIL", wait_hours=24, status="scheduled"),
                WorkflowStep(step=4, action="VOICE", wait_hours=24, status="scheduled"),
            ]
        if strategy.strategy == "SMS":
            return [
                WorkflowStep(step=1, action="SMS", wait_hours=0),
                WorkflowStep(step=2, action="WAIT", wait_hours=24, status="scheduled", detail="wait 24h"),
                WorkflowStep(step=3, action="EMAIL", wait_hours=24, status="scheduled"),
                WorkflowStep(step=4, action="VOICE", wait_hours=24, status="scheduled"),
            ]
        if strategy.strategy == "CALL":
            return [
                WorkflowStep(step=1, action="VOICE", wait_hours=0),
                WorkflowStep(step=2, action="WAIT", wait_hours=24, status="scheduled", detail="wait 24h"),
                WorkflowStep(step=3, action="SMS", wait_hours=24, status="scheduled"),
                WorkflowStep(step=4, action="EMAIL", wait_hours=24, status="scheduled"),
            ]
        if strategy.strategy == "OFFER":
            return [
                WorkflowStep(step=1, action="EMAIL", wait_hours=0, detail="send installment/discount offer"),
                WorkflowStep(step=2, action="WAIT", wait_hours=24, status="scheduled", detail="wait 24h"),
                WorkflowStep(step=3, action="SMS", wait_hours=24, status="scheduled"),
            ]
        if strategy.strategy == "ESCALATE":
            return [WorkflowStep(step=1, action="CRM", wait_hours=0, detail="human escalation")]
        return [WorkflowStep(step=1, action="WAIT", wait_hours=72, status="scheduled", detail="defer 72h")]

    async def _perform_action(self, txn: PaymentTransaction, step: WorkflowStep) -> str:
        if step.action == "SMS":
            content = build_recovery_sms(txn.customer.name, format_inr(txn.amount_inr))
            result = await get_sms_provider().send(txn.customer.phone, content)
            if not result.success:
                raise RuntimeError(result.detail or "sms send failed")
            return f"sms sent ({result.reference})"
        if step.action == "EMAIL":
            content = build_recovery_email(txn.customer.name, format_inr(txn.amount_inr))
            result = await get_email_provider().send(txn.customer.email, content)
            if not result.success:
                raise RuntimeError(result.detail or "email send failed")
            return f"email sent ({result.reference})"
        if step.action == "VOICE":
            script = build_hinglish_script(txn.customer.name, format_inr(txn.amount_inr))
            result = await get_voice_provider().place_call(txn.customer.phone, script)
            if not result.success:
                raise RuntimeError(result.detail or "voice call failed")
            return f"voice call placed ({result.reference})"
        if step.action == "RETRY":
            return "retry scheduled"
        if step.action == "CRM":
            return "human escalation created"
        return "scheduled"


class VerityAuditSupervisor(BaseAgent):
    name = "audit_supervisor"
    description = "Compliance gate and audit logging"
    system_prompt = AUDIT_SUPERVISOR_SYSTEM_PROMPT

    async def gate(
        self,
        *,
        merchant_id: str,
        user_id: Optional[str],
        txn: PaymentTransaction,
        analysis: PaymentAnalysisOutput,
        strategy: StrategyDecision,
        execution: Optional[ExecutionOutcome],
        contact_attempts: int,
        daily_spend_usd: float,
    ) -> AuditDecision:
        settings = get_settings()
        violations: List[str] = []
        if merchant_id in settings.blacklisted_merchant_id_set:
            violations.append("merchant is blacklisted")
        if contact_attempts >= 3:
            violations.append("max contact attempts reached")
        if daily_spend_usd >= settings.merchant_daily_spend_limit_usd:
            violations.append("daily merchant spending limit exceeded")
        if txn.customer.phone in settings.invalid_phone_number_set:
            violations.append("blacklisted phone number")
        if txn.amount_inr > 5000:
            violations.append("recovery amount exceeds $5000 human escalation threshold")

        approved = not violations
        reason = "all gates passed" if approved else "; ".join(violations)
        decision = AuditDecision(approved=approved, reason=reason, violations=violations)
        await self._persist_audit(
            merchant_id=merchant_id,
            user_id=user_id,
            txn=txn,
            analysis=analysis,
            strategy=strategy,
            execution=execution,
            decision=decision,
        )
        return decision

    async def _persist_audit(
        self,
        *,
        merchant_id: str,
        user_id: Optional[str],
        txn: PaymentTransaction,
        analysis: PaymentAnalysisOutput,
        strategy: StrategyDecision,
        execution: Optional[ExecutionOutcome],
        decision: AuditDecision,
    ) -> None:
        if self.db is not None:
            try:
                self.db.add(
                    AuditLog(
                        id=uuid.uuid4().hex,
                        merchant_id=merchant_id,
                        action_type="verity_recovery_decision",
                        input_data={
                            "payment_id": txn.payment_id,
                            "analysis": analysis.model_dump(mode="json"),
                            "strategy": strategy.model_dump(mode="json"),
                        },
                        output_data={
                            "execution": execution.model_dump(mode="json") if execution else None,
                            "audit": decision.model_dump(mode="json"),
                        },
                        model_confidence=decision.confidence,
                        timestamp=utcnow(),
                        user_id=user_id,
                    )
                )
                self.db.flush()
            except Exception as exc:  # noqa: BLE001
                logger.warning("verity.audit.persist_failed", error=str(exc))
        self.audit(
            event_type=self._audit_event_type(decision.approved),
            resource_type="merchant",
            resource_id=merchant_id,
            outcome="approved" if decision.approved else "rejected",
            message=decision.reason,
            details={
                "payment_id": txn.payment_id,
                "user_id": user_id,
                "violations": decision.violations,
            },
        )

    @staticmethod
    def _audit_event_type(approved: bool):
        from app.models.audit import AuditEventType

        return AuditEventType.RECOVERY_SUCCEEDED if approved else AuditEventType.RECOVERY_FAILED


class VerityGraphRunner:
    """Builds and runs the Verity LangGraph workflow."""

    def __init__(self, db: Session, emit: Optional[AsyncEmitter] = None):
        self.db = db
        self.emit = emit or self._noop_emit
        self.analyzer = VerityPaymentAnalyzer()
        self.selector = VerityStrategySelector()
        self.executor = VerityExecutionOrchestrator()
        self.audit = VerityAuditSupervisor()
        for agent in (self.analyzer, self.selector, self.executor, self.audit):
            agent.bind_db(db)
        self._graph = self._build_graph()

    async def _noop_emit(self, event: Dict[str, Any]) -> None:
        return None

    def _build_graph(self):
        builder: StateGraph[VerityState] = StateGraph(VerityState)

        async def payment_analyzer(state: VerityState):
            record = self._get_payment(state["payment_id"])
            txn = record.to_domain()
            analysis = await self.analyzer.analyze(txn)
            update = {
                "payment": record.public_view(),
                "analysis": analysis.model_dump(mode="json"),
                "confidence": analysis.confidence,
            }
            update.update(
                _append_trace(
                    state,
                    "PaymentAnalyzer",
                    f"root cause {analysis.primary_failure_reason['code']} at {analysis.confidence:.2f} confidence",
                    confidence=analysis.confidence,
                )
            )
            if analysis.confidence < state.get("confidence_threshold", get_settings().human_review_confidence_threshold):
                approved = interrupt(
                    {
                        "step": "PaymentAnalyzer",
                        "confidence": analysis.confidence,
                        "summary": analysis.reasoning_summary,
                        "question": "Low analyzer confidence. Continue?",
                    }
                )
                if isinstance(approved, dict) and not approved.get("approved", False):
                    return Command(update={**update, "stop_reason": "human rejected analyzer checkpoint"}, goto=END)
            await self.emit(
                {
                    "stage": "PaymentAnalyzer",
                    "summary": analysis.reasoning_summary,
                    "confidence": analysis.confidence,
                }
            )
            return update

        async def strategy_selector(state: VerityState):
            record = self._get_payment(state["payment_id"])
            txn = record.to_domain()
            analysis = PaymentAnalysisOutput(**state["analysis"])
            strategy = await self.selector.select(analysis, txn)
            update = {
                "strategy": strategy.model_dump(mode="json"),
            }
            update.update(
                _append_trace(
                    state,
                    "StrategySelector",
                    f"strategy {strategy.strategy} chosen with {strategy.confidence:.1f}% confidence",
                    strategy=strategy.strategy,
                    confidence=strategy.confidence,
                )
            )
            if strategy.confidence / 100.0 < state.get("confidence_threshold", get_settings().human_review_confidence_threshold):
                approved = interrupt(
                    {
                        "step": "StrategySelector",
                        "confidence": strategy.confidence,
                        "summary": strategy.rationale,
                        "question": "Low strategy confidence. Continue?",
                    }
                )
                if isinstance(approved, dict) and not approved.get("approved", False):
                    return Command(update={**update, "stop_reason": "human rejected strategy checkpoint"}, goto=END)
            await self.emit(
                {
                    "stage": "StrategySelector",
                    "summary": strategy.rationale,
                    "confidence": strategy.confidence,
                }
            )
            return update

        async def execution_orchestrator(state: VerityState):
            record = self._get_payment(state["payment_id"])
            txn = record.to_domain()
            analysis = PaymentAnalysisOutput(**state["analysis"])
            strategy = StrategyDecision(**state["strategy"])
            contact_attempts = state.get("contact_attempts", 0)
            daily_spend_usd = state.get("daily_spend_usd", 0.0)

            async def audit_gate(step_name: str, current_recovered: float) -> AuditDecision:
                return await self.audit.gate(
                    merchant_id=state["merchant_id"],
                    user_id=state.get("user_id"),
                    txn=txn,
                    analysis=analysis,
                    strategy=strategy,
                    execution=None,
                    contact_attempts=contact_attempts + 1,
                    daily_spend_usd=daily_spend_usd,
                )

            execution = await self.executor.execute(
                txn,
                analysis,
                strategy,
                dry_run=state.get("dry_run", True),
                audit_gate=audit_gate,
            )
            update = {
                "execution": execution.model_dump(mode="json"),
                "recovery_amount_usd": execution.money_recovered,
                "contact_attempts": contact_attempts + 1,
            }
            update.update(
                _append_trace(
                    state,
                    "ExecutionOrchestrator",
                    execution.summary,
                    channel_used=execution.channel_used,
                    money_recovered=execution.money_recovered,
                )
            )
            if strategy.confidence / 100.0 < state.get("confidence_threshold", get_settings().human_review_confidence_threshold):
                approved = interrupt(
                    {
                        "step": "ExecutionOrchestrator",
                        "confidence": strategy.confidence,
                        "summary": execution.summary,
                        "question": "Execution confidence is low. Continue?",
                    }
                )
                if isinstance(approved, dict) and not approved.get("approved", False):
                    return Command(update={**update, "stop_reason": "human rejected execution checkpoint"}, goto=END)
            await self.emit(
                {
                    "stage": "ExecutionOrchestrator",
                    "summary": execution.summary,
                    "workflow": [step.model_dump(mode="json") for step in execution.workflow],
                }
            )
            return update

        async def audit_supervisor(state: VerityState):
            record = self._get_payment(state["payment_id"])
            txn = record.to_domain()
            analysis = PaymentAnalysisOutput(**state["analysis"])
            strategy = StrategyDecision(**state["strategy"])
            execution = ExecutionOutcome(**state["execution"]) if state.get("execution") else None
            decision = await self.audit.gate(
                merchant_id=state["merchant_id"],
                user_id=state.get("user_id"),
                txn=txn,
                analysis=analysis,
                strategy=strategy,
                execution=execution,
                contact_attempts=state.get("contact_attempts", 0),
                daily_spend_usd=state.get("daily_spend_usd", 0.0),
            )
            update = {
                "audit": decision.model_dump(mode="json"),
                "approved": decision.approved,
            }
            update.update(
                _append_trace(
                    state,
                    "AuditSupervisor",
                    decision.reason,
                    approved=decision.approved,
                    violations=decision.violations,
                )
            )
            await self.emit(
                {
                    "stage": "AuditSupervisor",
                    "summary": decision.reason,
                    "approved": decision.approved,
                    "violations": decision.violations,
                }
            )
            return update

        builder.add_node("PaymentAnalyzer", payment_analyzer)
        builder.add_node("StrategySelector", strategy_selector)
        builder.add_node("ExecutionOrchestrator", execution_orchestrator)
        builder.add_node("AuditSupervisor", audit_supervisor)
        builder.add_edge(START, "PaymentAnalyzer")
        builder.add_edge("PaymentAnalyzer", "StrategySelector")
        builder.add_edge("StrategySelector", "ExecutionOrchestrator")
        builder.add_edge("ExecutionOrchestrator", "AuditSupervisor")
        builder.add_edge("AuditSupervisor", END)
        checkpointer = self._build_checkpointer()
        return builder.compile(checkpointer=checkpointer)

    def _build_checkpointer(self):
        settings = get_settings()
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = settings.verity_checkpoint_path
            if path.startswith("sqlite:///"):
                path = path.replace("sqlite:///", "", 1)
            sqlite_path = path
            if sqlite_path not in {":memory:", ""}:
                Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(sqlite_path, check_same_thread=False)
            return SqliteSaver(conn)
        except Exception:
            logger.warning("verity.checkpointer_fallback_memory")
            return MemorySaver()

    def _get_payment(self, payment_id: str) -> PaymentRecord:
        record = self.db.get(PaymentRecord, payment_id)
        if record is None:
            raise ValueError(f"payment '{payment_id}' not found")
        return record

    async def run(
        self,
        *,
        payment_id: str,
        merchant_id: str,
        user_id: Optional[str] = None,
        dry_run: bool = True,
        thread_id: Optional[str] = None,
        resume: Optional[Dict[str, Any]] = None,
        confidence_threshold: Optional[float] = None,
        contact_attempts: int = 0,
        daily_spend_usd: float = 0.0,
    ) -> Dict[str, Any]:
        run_thread_id = thread_id or uuid.uuid4().hex
        config = {
            "configurable": {
                "thread_id": run_thread_id,
            }
        }
        payload: Any = resume if resume is not None else {
            "payment_id": payment_id,
            "merchant_id": merchant_id,
            "user_id": user_id or "",
            "dry_run": dry_run,
            "confidence_threshold": confidence_threshold or get_settings().human_review_confidence_threshold,
            "trace": [],
            "contact_attempts": contact_attempts,
            "daily_spend_usd": daily_spend_usd,
        }
        result = await self._graph.ainvoke(payload, config=config)
        normalized = self._normalize_result(result)
        normalized["thread_id"] = run_thread_id
        return normalized

    @staticmethod
    def _normalize_result(result: Any) -> Dict[str, Any]:
        if isinstance(result, dict):
            if "__interrupt__" in result:
                return {
                    "interrupted": True,
                    "interrupts": result["__interrupt__"],
                    "state": {k: v for k, v in result.items() if k != "__interrupt__"},
                }
            return {"interrupted": False, "state": result}
        return {"interrupted": False, "state": result}


def _normalize_websocket_auth(websocket: WebSocket) -> bool:
    settings = get_settings()
    api_key = websocket.headers.get(settings.api_key_header.lower()) or websocket.headers.get("x-api-key")
    return bool(api_key and api_key in settings.valid_api_keys)
