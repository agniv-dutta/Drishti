"""ConsensusAgent - multi-agent weighted-vote decisions for high-value payments.

For payments above ``consensus_amount_threshold_inr`` (default Rs 50,000) three
persona agents deliberate in parallel:

- AggressiveRecoverer: immediate voice outreach, speed over cost
- ConservativeRecoverer: wait ~72h for card refresh, brand-safe digital nudges
- BalancedRecoverer: SMS first, escalate to voice if the nudge lapses

Each persona returns reasoning + confidence (0-100). The supervisor combines
them with a confidence-weighted vote and the winning strategy drives the plan.
Every recommendation and the final choice are written to the audit trail so
large-amount decisions stay fully transparent.

Works offline: when no Groq key is configured the personas emit deterministic,
analysis-driven recommendations instead of LLM debate.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent
from app.agents.prompts import (
    AGGRESSIVE_RECOVERER_PROMPT,
    BALANCED_RECOVERER_PROMPT,
    CONSENSUS_SYSTEM_PROMPT,
    CONSERVATIVE_RECOVERER_PROMPT,
)
from app.core.config import get_settings
from app.models.audit import AuditEventType, AuditSeverity
from app.models.payment import PaymentTransaction
from app.models.recovery import FailureAnalysis, RecoveryChannel, RecoveryStrategy


class AgentRecommendation(BaseModel):
    """One persona's verdict on how to recover a high-value payment."""

    agent_name: str
    strategy: RecoveryStrategy
    channels: List[RecoveryChannel]
    first_step_delay_minutes: int = 0
    confidence: float = Field(ge=0.0, le=100.0)
    reasoning: str = ""
    tradeoffs: str = ""
    source: str = "rule-engine"  # rule-engine | groq


class ConsensusDecision(BaseModel):
    """Weighted-vote outcome across all personas for one payment."""

    payment_id: str
    amount_inr: float
    threshold_inr: float
    recommendations: List[AgentRecommendation]
    winner_agent: str
    winning_strategy: RecoveryStrategy
    weighted_scores: Dict[str, float]
    agreement_ratio: float = Field(ge=0.0, le=1.0)
    decided_by: str = "weighted-vote"
    latency_ms: float = 0.0


# Tie-break order when weighted scores tie: balanced is the safest default.
_TIE_BREAK_PRIORITY = {
    "balanced_recoverer": 0,
    "conservative_recoverer": 1,
    "aggressive_recoverer": 2,
}


def _paise_payment_json(txn: PaymentTransaction, analysis: FailureAnalysis) -> str:
    """PII-safe payment snapshot for prompts/audit (no email/phone/name)."""
    return json.dumps(
        {
            "payment_id": txn.payment_id,
            "amount_inr": txn.amount_inr,
            "currency": txn.currency,
            "method": getattr(txn.method, "value", txn.method),
            "failure_reason": getattr(txn.failure_reason, "value", txn.failure_reason),
            "error_code": txn.error_code,
            "attempt_number": txn.attempt_number,
            "retryability": analysis.retryability.value,
            "risk_score": analysis.risk_score,
            "risk_band": analysis.risk_band,
            "suggested_wait_minutes": analysis.suggested_wait_minutes,
        },
        default=str,
    )


class PersonaRecoverer(BaseAgent):
    """Base for the three consensus personas."""

    system_prompt: str = ""
    default_strategy: RecoveryStrategy = RecoveryStrategy.NUDGE_DIGITAL
    default_channels: List[RecoveryChannel] = [RecoveryChannel.SMS]
    default_first_delay_minutes: int = 0

    async def run(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> AgentRecommendation:
        """BaseAgent contract - a persona's unit of work is its recommendation."""
        return await self.recommend(txn, analysis)

    async def recommend(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> AgentRecommendation:
        if self.llm_enabled:
            enriched = self._llm_recommend(txn, analysis)
            if enriched is not None:
                return enriched
        return self._rule_recommend(txn, analysis)

    # -- deterministic fallback ---------------------------------------
    def _rule_recommend(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> AgentRecommendation:
        raise NotImplementedError

    # -- LLM path ------------------------------------------------------
    def _llm_recommend(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> Optional[AgentRecommendation]:
        prompt = CONSENSUS_SYSTEM_PROMPT.format(payment_json=_paise_payment_json(txn, analysis))
        text = self.llm_complete(self.system_prompt, prompt)
        payload = self.extract_json(text)
        if not payload:
            return None

        strategy = _coerce_strategy(payload.get("strategy"))
        confidence = _coerce_confidence(payload.get("confidence"))
        if strategy is None or confidence is None:
            return None

        self.log.info("consensus.persona_llm", persona=self.name, confidence=confidence)
        return AgentRecommendation(
            agent_name=self.name,
            strategy=strategy,
            channels=self.default_channels,
            first_step_delay_minutes=self.default_first_delay_minutes,
            confidence=confidence,
            reasoning=str(payload.get("reasoning", ""))[:600],
            tradeoffs=str(payload.get("tradeoffs", ""))[:400],
            source="groq",
        )


def _coerce_strategy(value) -> Optional[RecoveryStrategy]:
    try:
        return RecoveryStrategy(str(value).strip().lower())
    except ValueError:
        return None


def _coerce_confidence(value) -> Optional[float]:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence <= 1.0:  # tolerate 0-1 scale outputs
        confidence *= 100.0
    return round(min(max(confidence, 0.0), 100.0), 1)


class AggressiveRecoverer(PersonaRecoverer):
    name = "aggressive_recoverer"
    description = "Speed-first: immediate voice outreach on large failures"
    system_prompt = AGGRESSIVE_RECOVERER_PROMPT
    default_strategy = RecoveryStrategy.HIGH_TOUCH_VOICE
    default_channels = [RecoveryChannel.VOICE_IVR, RecoveryChannel.CRM_ESCALATION]
    default_first_delay_minutes = 0

    def _rule_recommend(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> AgentRecommendation:
        # Urgency scales with risk plus ticket size (relative to consensus threshold).
        amount_factor = min(txn.amount_inr / get_settings().consensus_amount_threshold_inr, 3.0) * 0.03
        urgency = min(0.95, 0.6 + 0.3 * analysis.risk_score + amount_factor)
        return AgentRecommendation(
            agent_name=self.name,
            strategy=self.default_strategy,
            channels=self.default_channels,
            first_step_delay_minutes=self.default_first_delay_minutes,
            confidence=round(urgency * 100, 1),
            reasoning=(
                f"High-value failure ({txn.amount_inr:.0f} INR, risk {analysis.risk_score:.2f}). "
                f"Immediate voice outreach maximises contact rate while intent to pay is fresh; "
                f"every hour of delay erodes recovery odds on tickets this size."
            ),
            tradeoffs=(
                "Highest per-contact cost (IVR+agent), but fastest path to capital; "
                "moderate irritation risk mitigated by single well-timed call."
            ),
        )


class ConservativeRecoverer(PersonaRecoverer):
    name = "conservative_recoverer"
    description = "Brand-safe: wait ~72h for card refresh before retrying"
    system_prompt = CONSERVATIVE_RECOVERER_PROMPT
    default_strategy = RecoveryStrategy.SMART_RETRY
    default_channels = [RecoveryChannel.GATEWAY_RETRY]
    default_first_delay_minutes = 72 * 60

    def _rule_recommend(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> AgentRecommendation:
        patience = min(0.9, 0.55 + 0.25 * (1.0 - analysis.risk_score))
        return AgentRecommendation(
            agent_name=self.name,
            strategy=self.default_strategy,
            channels=self.default_channels,
            first_step_delay_minutes=self.default_first_delay_minutes,
            confidence=round(patience * 100, 1),
            reasoning=(
                f"Wait 72h so salary credit / card limit refresh clears the way, then a single "
                f"silent gateway retry. Preserves trust with high-value customers; "
                f"'{analysis.root_cause.value}' failures often self-resolve within days."
            ),
            tradeoffs=(
                "Near-zero contact cost and zero irritation, but slowest capital recovery "
                "and small drop-off risk if customer forgets."
            ),
        )


class BalancedRecoverer(PersonaRecoverer):
    name = "balanced_recoverer"
    description = "Expected-value: cheap SMS nudge first, voice escalation second"
    system_prompt = BALANCED_RECOVERER_PROMPT
    default_strategy = RecoveryStrategy.NUDGE_DIGITAL
    default_channels = [RecoveryChannel.SMS, RecoveryChannel.VOICE_IVR, RecoveryChannel.EMAIL]
    default_first_delay_minutes = 30

    def _rule_recommend(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> AgentRecommendation:
        balance = min(0.92, 0.58 + 0.22 * analysis.risk_score)
        return AgentRecommendation(
            agent_name=self.name,
            strategy=self.default_strategy,
            channels=self.default_channels,
            first_step_delay_minutes=self.default_first_delay_minutes,
            confidence=round(balance * 100, 1),
            reasoning=(
                f"Low-friction SMS with payment link converts most soft declines at trivial cost; "
                f"escalate to voice after {self.default_first_delay_minutes} minutes if unanswered, "
                f"email as final touch. Risk band '{analysis.risk_band}' supports staged outreach."
            ),
            tradeoffs=(
                "Best cost-to-speed ratio and gentle on the customer; concedes some speed "
                "versus immediate calling in exchange for much lower spend."
            ),
        )


class ConsensusAgent(BaseAgent):
    """Runs the three-persona debate and resolves a weighted-vote winner."""

    name = "consensus"
    description = "Weighted multi-agent verdict for high-value recoveries"
    system_prompt = CONSENSUS_SYSTEM_PROMPT

    def __init__(self) -> None:
        super().__init__()
        self.personas: List[PersonaRecoverer] = [
            AggressiveRecoverer(),
            ConservativeRecoverer(),
            BalancedRecoverer(),
        ]

    # ------------------------------------------------------------------
    def applies(self, txn: PaymentTransaction) -> bool:
        settings = get_settings()
        return bool(settings.consensus_enabled) and txn.amount_inr > settings.consensus_amount_threshold_inr

    async def run(self, txn: PaymentTransaction, analysis: FailureAnalysis) -> ConsensusDecision:
        started = time.perf_counter()
        settings = get_settings()

        recommendations: List[AgentRecommendation] = await asyncio.gather(
            *(persona.recommend(txn, analysis) for persona in self.personas)
        )

        weighted_scores: Dict[str, float] = {}
        total_weight = 0.0
        best_name = ""
        best_key: Optional[Tuple[float, int]] = None
        for rec in recommendations:
            score = rec.confidence  # equal base weight x confidence
            weighted_scores[rec.agent_name] = round(score, 2)
            total_weight += score
            # Higher score wins; on ties the safer persona wins (balanced first).
            candidate_key = (score, -_TIE_BREAK_PRIORITY.get(rec.agent_name, 99))
            if best_key is None or candidate_key > best_key:
                best_name = rec.agent_name
                best_key = candidate_key

        winner = next(r for r in recommendations if r.agent_name == best_name)
        agreement = round(weighted_scores[best_name] / total_weight, 4) if total_weight > 0 else 0.0

        decision = ConsensusDecision(
            payment_id=txn.payment_id,
            amount_inr=txn.amount_inr,
            threshold_inr=settings.consensus_amount_threshold_inr,
            recommendations=recommendations,
            winner_agent=winner.agent_name,
            winning_strategy=winner.strategy,
            weighted_scores=weighted_scores,
            agreement_ratio=agreement,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

        severity = AuditSeverity.INFO if agreement >= 0.5 else AuditSeverity.WARNING
        self.audit(
            AuditEventType.CONSENSUS_REACHED,
            resource_type="payment",
            resource_id=txn.payment_id,
            outcome=f"winner={winner.agent_name}:{winner.strategy.value}",
            severity=severity,
            message=(
                f"consensus over Rs {txn.amount_inr:,.0f}: "
                f"{', '.join(f'{r.agent_name}->{r.strategy.value}@{r.confidence:.0f}' for r in recommendations)}"
            ),
            details={
                "amount_inr": txn.amount_inr,
                "threshold_inr": decision.threshold_inr,
                "recommendations": [rec.model_dump(mode="json") for rec in recommendations],
                "weighted_scores": weighted_scores,
                "winner_agent": winner.agent_name,
                "winning_strategy": winner.strategy.value,
                "agreement_ratio": agreement,
                "latency_ms": decision.latency_ms,
            },
        )
        return decision


_consensus: Optional[ConsensusAgent] = None


def get_consensus_agent() -> ConsensusAgent:
    global _consensus
    if _consensus is None:
        _consensus = ConsensusAgent()
    return _consensus
