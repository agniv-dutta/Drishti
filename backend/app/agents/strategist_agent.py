"""StrategistAgent - converts a FailureAnalysis into a costed RecoveryPlan."""

from __future__ import annotations

import math
import time
import uuid
from typing import Dict, List, Optional, Tuple

from app.agents.base_agent import BaseAgent
from app.agents.consensus_agent import ConsensusDecision
from app.agents.prompts import STRATEGY_SELECTOR_SYSTEM_PROMPT
from app.core.config import get_settings
from app.ml.data_preprocessor import build_features, build_strategy_features
from app.ml.recovery_classifier import get_recovery_classifier
from app.models.audit import AuditEventType
from app.models.payment import PaymentTransaction
from app.models.recovery import (
    FailureAnalysis,
    RecoveryChannel,
    RecoveryPlan,
    RecoveryStep,
    RecoveryStrategy,
    step_cost,
)


def _union_probability(probabilities: List[float]) -> float:
    """P(at least one of the independent-ish channels converts)."""
    survival = 1.0
    for p in probabilities:
        survival *= 1.0 - min(max(p, 0.0), 0.99)
    return round(1.0 - survival, 4)


class StrategistAgent(BaseAgent):
    name = "strategist"
    description = "Selects the recovery strategy and sequences outreach channels"
    system_prompt = STRATEGY_SELECTOR_SYSTEM_PROMPT

    async def run(
        self,
        txn: PaymentTransaction,
        analysis: FailureAnalysis,
        override_strategy: Optional[RecoveryStrategy] = None,
    ) -> RecoveryPlan:
        started = time.perf_counter()
        settings = get_settings()
        classifier = get_recovery_classifier()
        features = build_features(txn)

        ranked = classifier.rank_channels(analysis.retryability, features)
        strategy = override_strategy or classifier.choose_strategy(
            retryability=analysis.retryability,
            risk_score=analysis.risk_score,
            amount_inr=txn.amount_inr,
            high_value_threshold_inr=settings.high_value_threshold_inr,
        )

        # The trained strategy classifier overrides the heuristic choice only when confident.
        if override_strategy is None and classifier.using_ml_model:
            metadata = txn.meta
            strategy_features = build_strategy_features(
                decline_reason=(txn.failure_reason.value if txn.failure_reason else "unknown"),
                customer_segment=metadata.get("customer_segment", "new"),
                failure_count=metadata.get("failure_count", max(txn.attempt_number - 1, 0)),
                time_since_last_attempt=metadata.get("time_since_last_attempt", 0.0),
                customer_communication_preference=metadata.get(
                    "customer_communication_preference", "none"
                ),
            )
            prediction = classifier.predict_strategy(strategy_features)
            strategy = {
                "retry": RecoveryStrategy.SMART_RETRY,
                "sms": RecoveryStrategy.NUDGE_DIGITAL,
                "call": RecoveryStrategy.HIGH_TOUCH_VOICE,
                "offer": RecoveryStrategy.NUDGE_DIGITAL,
                "escalate": RecoveryStrategy.CRM_HUMAN_ESCALATION,
            }.get(prediction["recommended_strategy"], strategy)

        # Feedback loop: weekly outcome data can overrule heuristics/ML when a
        # strategy clearly outperforms for this failure reason (no retraining).
        learning_note = ""
        if override_strategy is None:
            learned, learning_note = await self._learned_strategy_override(txn, strategy)
            if learned is not None:
                strategy = learned

        steps = self._build_steps(strategy, analysis, ranked, txn.amount_inr, settings.high_value_threshold_inr)
        total_cost = sum(step.estimated_cost_paise for step in steps)
        expected_success = self._expected_success(strategy, analysis, ranked)

        rationale = self._rationale(strategy, analysis, ranked)
        if learning_note:
            rationale = f"{rationale} Feedback loop: {learning_note}"

        plan = RecoveryPlan(
            plan_id=uuid.uuid4().hex,
            payment_id=txn.payment_id,
            strategy=strategy,
            steps=steps,
            expected_success_probability=expected_success,
            total_estimated_cost_paise=total_cost,
            rationale=rationale,
            created_by=self.name,
        )

        self.audit(
            AuditEventType.RECOVERY_PLAN_CREATED,
            resource_type="recovery",
            resource_id=plan.plan_id,
            outcome=strategy.value,
            details={
                "payment_id": txn.payment_id,
                "step_count": len(steps),
                "estimated_cost_paise": total_cost,
                "expected_success_probability": expected_success,
                "learning_applied": learning_note or None,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return plan

    async def _learned_strategy_override(
        self,
        txn: PaymentTransaction,
        current: RecoveryStrategy,
    ) -> Tuple[Optional[RecoveryStrategy], str]:
        """Switch strategy when weekly outcome data strongly favours another one."""
        try:
            from app.ml.feedback import TACTIC_LABELS, get_learning_snapshot

            snapshot = await get_learning_snapshot()
            reason = txn.failure_reason.value if txn.failure_reason else "unknown"
            info = (snapshot or {}).get("by_failure_reason", {}).get(reason)
            if not info:
                return None, ""

            ranking = [r for r in info.get("ranking", []) if r["tactic"] != "write_off"]
            if not ranking:
                return None, ""

            tactic_to_strategy = {
                tactic: strat
                for strat, tactic in TACTIC_LABELS.items()
                if tactic != "write_off"
            }
            best = ranking[0]
            current_tactic = TACTIC_LABELS.get(current.value, current.value)
            current_stats = next(
                (r for r in ranking if r["tactic"] == current_tactic), None
            )
            margin = best["success_rate"] - (current_stats["success_rate"] if current_stats else 0.0)
            if best["attempts"] >= 10 and best["success_rate"] >= 0.6 and margin >= 0.1:
                target = tactic_to_strategy.get(best["tactic"])
                if target is not None and target != current:
                    note = (
                        f"{reason}: {best['tactic']} wins at "
                        f"{round(best['success_rate'] * 100)}% success over "
                        f"{best['attempts']} attempts - overriding heuristic choice."
                    )
                    return target, note
        except Exception as exc:  # noqa: BLE001 - never break planning on learning errors
            self.log.warning("learning.override_failed", error=str(exc))
        return None, ""

    async def run_from_consensus(
        self,
        txn: PaymentTransaction,
        analysis: FailureAnalysis,
        decision: ConsensusDecision,
    ) -> RecoveryPlan:
        """Build the plan from a ConsensusAgent weighted-vote outcome."""
        started = time.perf_counter()
        classifier = get_recovery_classifier()
        ranked = classifier.rank_channels(analysis.retryability, build_features(txn))
        winner = next(r for r in decision.recommendations if r.agent_name == decision.winner_agent)

        steps = self._steps_from_channels(winner.channels, winner.first_step_delay_minutes, analysis)
        total_cost = sum(step.estimated_cost_paise for step in steps)
        expected_success = self._expected_success(winner.strategy, analysis, ranked)
        rationale = self._consensus_rationale(decision)

        plan = RecoveryPlan(
            plan_id=uuid.uuid4().hex,
            payment_id=txn.payment_id,
            strategy=winner.strategy,
            steps=steps,
            expected_success_probability=expected_success,
            total_estimated_cost_paise=total_cost,
            rationale=rationale,
            created_by=f"{self.name}+consensus({decision.winner_agent})",
        )

        self.audit(
            AuditEventType.RECOVERY_PLAN_CREATED,
            resource_type="recovery",
            resource_id=plan.plan_id,
            outcome=winner.strategy.value,
            details={
                "payment_id": txn.payment_id,
                "step_count": len(steps),
                "estimated_cost_paise": total_cost,
                "expected_success_probability": expected_success,
                "consensus_winner": decision.winner_agent,
                "agreement_ratio": decision.agreement_ratio,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return plan

    def _steps_from_channels(
        self,
        channels: List[RecoveryChannel],
        first_delay_minutes: int,
        analysis: FailureAnalysis,
    ) -> List[RecoveryStep]:
        gap = max(analysis.suggested_wait_minutes // max(len(channels) - 1, 1), 60) if len(channels) > 1 else 0
        steps: List[RecoveryStep] = []
        for index, channel in enumerate(channels):
            delay = first_delay_minutes if index == 0 else min(
                first_delay_minutes + gap * index,
                first_delay_minutes + 60 * 24 * 3,  # never stretch beyond 3 days
            )
            steps.append(
                RecoveryStep(
                    sequence=index + 1,
                    channel=channel,
                    delay_minutes=delay,
                    estimated_cost_paise=step_cost(channel),
                )
            )
        return steps

    def _consensus_rationale(self, decision: ConsensusDecision) -> str:
        votes = "; ".join(
            f"{rec.agent_name}={rec.strategy.value}@{rec.confidence:.0f}%"
            for rec in sorted(
                decision.recommendations,
                key=lambda r: decision.weighted_scores.get(r.agent_name, 0.0),
                reverse=True,
            )
        )
        return (
            f"Multi-agent consensus on Rs {decision.amount_inr:,.0f} failure "
            f"(threshold Rs {decision.threshold_inr:,.0f}). Votes: {votes}. "
            f"Winner {decision.winner_agent} -> {decision.winning_strategy.value} "
            f"(weighted agreement {decision.agreement_ratio:.0%})."
        )

    # ------------------------------------------------------------------
    def _build_steps(
        self,
        strategy: RecoveryStrategy,
        analysis: FailureAnalysis,
        ranked: List[Tuple[RecoveryChannel, float]],
        amount_inr: float,
        high_value_threshold_inr: float,
    ) -> List[RecoveryStep]:
        def make(sequence: int, channel: RecoveryChannel, delay_minutes: int) -> RecoveryStep:
            return RecoveryStep(
                sequence=sequence,
                channel=channel,
                delay_minutes=delay_minutes,
                estimated_cost_paise=step_cost(channel),
            )

        if strategy == RecoveryStrategy.SMART_RETRY:
            return [make(1, RecoveryChannel.GATEWAY_RETRY, analysis.suggested_wait_minutes)]

        if strategy == RecoveryStrategy.NUDGE_DIGITAL:
            return [
                make(1, RecoveryChannel.EMAIL, 0),
                make(2, RecoveryChannel.SMS, 30),
                make(3, RecoveryChannel.GATEWAY_RETRY, max(analysis.suggested_wait_minutes, 120)),
            ]

        if strategy == RecoveryStrategy.HIGH_TOUCH_VOICE:
            steps = [
                make(1, RecoveryChannel.SMS, 0),
                make(2, RecoveryChannel.VOICE_IVR, 60),
                make(3, RecoveryChannel.EMAIL, 240),
            ]
            if amount_inr >= high_value_threshold_inr:
                steps.append(make(4, RecoveryChannel.CRM_ESCALATION, 1440))
            return steps

        if strategy == RecoveryStrategy.CRM_HUMAN_ESCALATION:
            return [make(1, RecoveryChannel.CRM_ESCALATION, 0)]

        return []  # WRITE_OFF - terminal, no spend

    def _expected_success(
        self,
        strategy: RecoveryStrategy,
        analysis: FailureAnalysis,
        ranked: List[Tuple[RecoveryChannel, float]],
    ) -> float:
        by_channel: Dict[RecoveryChannel, float] = dict(ranked)
        if strategy == RecoveryStrategy.WRITE_OFF:
            base = 0.0
        elif strategy == RecoveryStrategy.SMART_RETRY:
            base = by_channel.get(RecoveryChannel.GATEWAY_RETRY, 0.55)
        elif strategy == RecoveryStrategy.NUDGE_DIGITAL:
            base = _union_probability([
                by_channel.get(RecoveryChannel.EMAIL, 0.45),
                by_channel.get(RecoveryChannel.SMS, 0.5),
                by_channel.get(RecoveryChannel.GATEWAY_RETRY, 0.55),
            ])
        elif strategy == RecoveryStrategy.HIGH_TOUCH_VOICE:
            base = _union_probability([
                by_channel.get(RecoveryChannel.SMS, 0.5),
                by_channel.get(RecoveryChannel.VOICE_IVR, 0.42),
                by_channel.get(RecoveryChannel.EMAIL, 0.45),
                by_channel.get(RecoveryChannel.CRM_ESCALATION, 0.28),
            ])
        else:  # CRM_HUMAN_ESCALATION
            base = by_channel.get(RecoveryChannel.CRM_ESCALATION, 0.25)

        # Blend channel model with the analyzer's overall recovery likelihood.
        blended = 0.65 * base + 0.35 * analysis.risk_score
        return round(min(max(blended, 0.01), 0.97), 4)

    def _rationale(
        self,
        strategy: RecoveryStrategy,
        analysis: FailureAnalysis,
        ranked: List[Tuple[RecoveryChannel, float]],
    ) -> str:
        top_channels = ", ".join(f"{c.value} ({p:.0%})" for c, p in ranked[:3])
        return (
            f"Root cause '{analysis.root_cause.value}' implies {analysis.retryability.value}; "
            f"risk band '{analysis.risk_band}' ({analysis.risk_score:.2f}). "
            f"Selected {strategy.value}. Channel ranking: {top_channels}."
        )
