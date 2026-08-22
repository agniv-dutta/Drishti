"""StrategistAgent - converts a FailureAnalysis into a costed RecoveryPlan."""

from __future__ import annotations

import math
import time
import uuid
from typing import Dict, List, Optional, Tuple

from app.agents.base_agent import BaseAgent
from app.agents.prompts import STRATEGY_SELECTOR_SYSTEM_PROMPT
from app.core.config import get_settings
from app.ml.data_preprocessor import build_features
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

        # Trained AutoML classifier can override the rule-based choice when confident.
        if override_strategy is None and classifier.using_ml_model:
            ml_ranked = classifier.predict_proba(txn, features)
            if ml_ranked and ml_ranked[0][1] >= 0.60:
                try:
                    strategy = RecoveryStrategy(ml_ranked[0][0])
                except ValueError:
                    pass  # unknown class label -> keep heuristic choice

        steps = self._build_steps(strategy, analysis, ranked, txn.amount_inr, settings.high_value_threshold_inr)
        total_cost = sum(step.estimated_cost_paise for step in steps)
        expected_success = self._expected_success(strategy, analysis, ranked)

        plan = RecoveryPlan(
            plan_id=uuid.uuid4().hex,
            payment_id=txn.payment_id,
            strategy=strategy,
            steps=steps,
            expected_success_probability=expected_success,
            total_estimated_cost_paise=total_cost,
            rationale=self._rationale(strategy, analysis, ranked),
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
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return plan

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
