"""Multi-agent consensus mechanism for high-value payments (> Rs 50,000)."""

from __future__ import annotations

import json

import pytest

from app.agents.consensus_agent import (
    AggressiveRecoverer,
    BalancedRecoverer,
    ConsensusAgent,
    ConservativeRecoverer,
)
from app.core.config import get_settings
from app.core.logging_config import get_audit_trail
from app.models.payment import (
    CustomerInfo,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
)
from app.models.recovery import FailureAnalysis, RecoveryStrategy, Retryability


def make_txn(amount_inr: float = 60_000.0) -> PaymentTransaction:
    return PaymentTransaction(
        payment_id="pay_consensus_1",
        order_id="order_consensus_1",
        customer=CustomerInfo(name="Test User", email="t@example.com", phone="+919876543210"),
        amount_paise=int(amount_inr * 100),
        method=PaymentMethod.CARD,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.BANK_DECLINE,
        error_code="gateway_declined",
        attempt_number=1,
    )


def make_analysis(risk_score: float = 0.7) -> FailureAnalysis:
    return FailureAnalysis(
        payment_id="pay_consensus_1",
        root_cause=FailureReason.BANK_DECLINE,
        retryability=Retryability.DELAYED_RETRY,
        confidence=0.9,
        reasoning=["test"],
        risk_score=risk_score,
        risk_band="high" if risk_score >= 0.65 else "medium",
        suggested_wait_minutes=240,
        analyzed_by="rule-engine",
    )


class TestThresholdGating:
    def test_applies_above_threshold(self):
        agent = ConsensusAgent()
        assert agent.applies(make_txn(60_000)) is True

    def test_skips_below_threshold(self):
        agent = ConsensusAgent()
        assert agent.applies(make_txn(5_000)) is False

    def test_threshold_boundary_is_exclusive(self):
        settings = get_settings()
        agent = ConsensusAgent()
        assert agent.applies(make_txn(settings.consensus_amount_threshold_inr)) is False


class TestWeightedVote:
    @pytest.mark.asyncio
    async def test_three_parallel_recommendations(self):
        decision = await ConsensusAgent().run(make_txn(), make_analysis())

        names = {r.agent_name for r in decision.recommendations}
        assert names == {"aggressive_recoverer", "conservative_recoverer", "balanced_recoverer"}
        assert all(rec.reasoning for rec in decision.recommendations)
        assert all(0 < rec.confidence <= 100 for rec in decision.recommendations)

    @pytest.mark.asyncio
    async def test_persona_strategies(self):
        decision = await ConsensusAgent().run(make_txn(), make_analysis())
        by_name = {r.agent_name: r.strategy for r in decision.recommendations}

        assert by_name["aggressive_recoverer"] == RecoveryStrategy.HIGH_TOUCH_VOICE
        assert by_name["conservative_recoverer"] == RecoveryStrategy.SMART_RETRY
        assert by_name["balanced_recoverer"] == RecoveryStrategy.NUDGE_DIGITAL

    @pytest.mark.asyncio
    async def test_conservative_waits_72h(self):
        decision = await ConsensusAgent().run(make_txn(), make_analysis())
        conservative = next(
            r for r in decision.recommendations if r.agent_name == "conservative_recoverer"
        )
        assert conservative.first_step_delay_minutes == 72 * 60

    @pytest.mark.asyncio
    async def test_winner_has_max_weighted_score(self):
        decision = await ConsensusAgent().run(make_txn(), make_analysis())

        winner_rec = next(r for r in decision.recommendations if r.agent_name == decision.winner_agent)
        top_score = max(decision.weighted_scores.values())

        assert decision.winning_strategy == winner_rec.strategy
        assert decision.weighted_scores[decision.winner_agent] == pytest.approx(top_score)
        assert 1 / 3 <= decision.agreement_ratio <= 1.0

    @pytest.mark.asyncio
    async def test_high_risk_tips_vote_to_aggressive(self):
        """At very high risk the aggressive persona's confidence dominates."""
        decision = await ConsensusAgent().run(make_txn(), make_analysis(risk_score=0.95))
        assert decision.winner_agent == "aggressive_recoverer"

    @pytest.mark.asyncio
    async def test_low_risk_tips_vote_to_conservative(self):
        decision = await ConsensusAgent().run(make_txn(), make_analysis(risk_score=0.2))
        assert decision.winner_agent == "conservative_recoverer"


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_debate_logged_to_jsonl(self):
        decision = await ConsensusAgent().run(make_txn(), make_analysis())

        trail_path = get_audit_trail().path
        events = [json.loads(line) for line in trail_path.read_text(encoding="utf-8").splitlines()]
        consensus_events = [e for e in events if e.get("event_type") == "consensus_reached"]
        assert consensus_events, "expected a consensus_reached audit event"

        entry = consensus_events[-1]
        details = entry.get("details") or {}
        recs = details.get("recommendations", [])
        assert len(recs) == 3
        assert details.get("winner_agent") == decision.winner_agent
        assert details.get("winning_strategy") == decision.winning_strategy.value
        assert set(details.get("weighted_scores", {})) == {
            "aggressive_recoverer",
            "conservative_recoverer",
            "balanced_recoverer",
        }


class TestLLMEnrichment:
    @pytest.mark.asyncio
    async def test_llm_payload_parsed(self, monkeypatch):
        persona = BalancedRecoverer()
        # Tests run with GROQ_API_KEY="" so force the LLM path on for this unit test.
        monkeypatch.setattr(
            BalancedRecoverer, "llm_enabled", property(lambda self: True)
        )
        monkeypatch.setattr(
            persona,
            "llm_complete",
            lambda system, prompt: json.dumps(
                {
                    "strategy": "high_touch_voice",
                    "confidence": 81,
                    "reasoning": "Voice converts high tickets fastest.",
                    "tradeoffs": "Cost up, speed up.",
                }
            ),
        )
        rec = await persona.recommend(make_txn(), make_analysis())
        assert rec.source == "groq"
        assert rec.strategy == RecoveryStrategy.HIGH_TOUCH_VOICE
        assert rec.confidence == 81.0
        assert "voice" in rec.reasoning.lower()

    @pytest.mark.asyncio
    async def test_garbage_llm_output_falls_back_to_rules(self, monkeypatch):
        persona = AggressiveRecoverer()
        monkeypatch.setattr(persona, "llm_complete", lambda system, prompt: "not json at all")
        rec = await persona.recommend(make_txn(), make_analysis())
        assert rec.source == "rule-engine"
        assert rec.strategy == RecoveryStrategy.HIGH_TOUCH_VOICE

    @pytest.mark.asyncio
    async def test_unknown_strategy_rejected_falls_back(self, monkeypatch):
        persona = ConservativeRecoverer()
        monkeypatch.setattr(
            persona,
            "llm_complete",
            lambda system, prompt: json.dumps({"strategy": "yell_at_customer", "confidence": 99}),
        )
        rec = await persona.recommend(make_txn(), make_analysis())
        assert rec.source == "rule-engine"
        assert rec.first_step_delay_minutes == 72 * 60


class TestConsensusPlanIntegration:
    @pytest.mark.asyncio
    async def test_plan_built_from_consensus(self):
        from app.agents.strategist_agent import StrategistAgent

        txn = make_txn()
        analysis = make_analysis()
        decision = await ConsensusAgent().run(txn, analysis)

        plan = await StrategistAgent().run_from_consensus(txn, analysis, decision)
        winner = next(r for r in decision.recommendations if r.agent_name == decision.winner_agent)

        assert plan.payment_id == txn.payment_id
        assert plan.strategy == winner.strategy
        assert [s.channel for s in plan.steps] == winner.channels
        assert plan.steps[0].delay_minutes == winner.first_step_delay_minutes
        assert plan.total_estimated_cost_paise > 0
        assert "Multi-agent consensus" in plan.rationale
        assert decision.winner_agent in plan.created_by

    @pytest.mark.asyncio
    async def test_supervisor_build_plan_routes_through_consensus(self, client, api_key):
        """API-level: a Rs 60k failure must be planned by the consensus panel."""
        payload = {
            "order_id": "order_consensus_api_1",
            "gateway_payment_id": "payGWCONSENSUS1",
            "customer": {"name": "Big Ticket", "email": "big@example.com", "phone": "+919812345678"},
            "amount": 60_000.0,
            "currency": "INR",
            "method": "card",
            "status": "failed",
            "failure_reason_code": "gateway_declined",
            "error_description": "Issuer declined at authorization",
            "attempt_number": 1,
            "metadata": {"source": "consensus-test"},
        }
        ingest = client.post("/api/v1/payment/ingest", json=payload)
        assert ingest.status_code == 200, ingest.text
        payment_id = ingest.json()["payment_id"]

        plan_resp = client.post("/api/v1/recovery/plan", json={"payment_id": payment_id})
        assert plan_resp.status_code == 200, plan_resp.text

        plan = plan_resp.json()["plan"]
        assert "Multi-agent consensus" in plan["rationale"]
        assert plan["created_by"].startswith("strategist+consensus(")
        assert plan["strategy"] in {"smart_retry", "nudge_digital", "high_touch_voice"}

        trail_path = get_audit_trail().path
        events = [json.loads(line) for line in trail_path.read_text(encoding="utf-8").splitlines()]
        assert any(e.get("event_type") == "consensus_reached" for e in events)
