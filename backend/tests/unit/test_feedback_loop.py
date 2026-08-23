"""Feedback loop: attempt logging, weekly aggregation, dynamic prompts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, LearningEventRecord
from app.database.session import get_engine
from app.models.recovery import ExecutionResult, RecoveryChannel, RecoveryPlan, RecoveryStep, RecoveryStrategy, StepOutcome, StepStatus
from app.ml.feedback import (
    CustomerResponse,
    FeedbackLoop,
    classify_response,
    infer_happiness,
    time_bucket,
)

DT = datetime(2026, 8, 20, 10, 30, tzinfo=timezone.utc)


def _plan(strategy: RecoveryStrategy = RecoveryStrategy.NUDGE_DIGITAL) -> RecoveryPlan:
    return RecoveryPlan(
        plan_id=uuid.uuid4().hex,
        payment_id="pay_fb_1",
        strategy=strategy,
        steps=[RecoveryStep(sequence=1, channel=RecoveryChannel.SMS, delay_minutes=0, estimated_cost_paise=10)],
        created_at=DT,
    )


def _result(
    success: bool = True,
    recovered: int = 100,
    details: str = "sent",
) -> ExecutionResult:
    outcome = StepOutcome(
        sequence=1,
        channel=RecoveryChannel.SMS,
        status=StepStatus.SUCCEEDED if success else StepStatus.FAILED,
        detail=details,
        recovered_amount_paise=recovered if success else 0,
    )
    res = ExecutionResult(
        plan_id="plan_x",
        payment_id="pay_fb_1",
        success=success,
        outcomes=[outcome],
        total_cost_paise=10,
        recovered_amount_paise=recovered if success else 0,
        summary="ok",
    )
    res.completed_at = DT
    return res


class TestClassifyResponse:
    def test_success(self):
        assert classify_response(_result(success=True), {}) == CustomerResponse.SUCCESS

    def test_no_response_default(self):
        assert classify_response(_result(success=False, details="provider timeout"), {}) == CustomerResponse.NO_RESPONSE

    def test_opted_out_marker(self):
        assert (
            classify_response(_result(success=False, details="customer replied STOP unsubscribe"), {})
            == CustomerResponse.OPTED_OUT
        )

    def test_complained_marker(self):
        assert (
            classify_response(_result(success=False, details="customer angry, filed complain"), {})
            == CustomerResponse.COMPLAINED
        )

    def test_explicit_meta_override_wins(self):
        assert classify_response(_result(success=False), {"customer_response": "opted_out"}) == CustomerResponse.OPTED_OUT

    def test_invalid_override_ignored(self):
        assert classify_response(_result(success=True), {"customer_response": "bogus"}) == CustomerResponse.SUCCESS


class TestHappinessAndTime:
    def test_happiness_ordering(self):
        assert infer_happiness(CustomerResponse.SUCCESS) > infer_happiness(CustomerResponse.NO_RESPONSE)
        assert infer_happiness(CustomerResponse.NO_RESPONSE) > infer_happiness(CustomerResponse.COMPLAINED)
        assert 0.0 <= infer_happiness(CustomerResponse.COMPLAINED, support_tickets=99) <= 1.0

    def test_time_buckets(self):
        assert time_bucket(DT) == "morning"
        assert time_bucket(DT.replace(hour=14)) == "afternoon"
        assert time_bucket(DT.replace(hour=18)) == "evening"
        assert time_bucket(DT.replace(hour=2)) == "night"


class TestLogAttemptAndAggregate:
    @pytest.fixture
    def db(self):
        Base.metadata.create_all(get_engine())  # idempotent
        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        session = factory()
        yield session
        session.close()

    def _seed(self, db, rows: List[tuple]):
        """rows of (reason, strategy, succeeded, n)."""
        for reason, strategy, succeeded, n in rows:
            for i in range(n):
                db.add(
                    LearningEventRecord(
                        id=uuid.uuid4().hex,
                        created_at=DT,
                        payment_id=f"pay_{reason}_{strategy}_{i}",
                        recovery_id=f"rec_{i}",
                        strategy=strategy,
                        channel="sms",
                        customer_response=CustomerResponse.SUCCESS.value if succeeded else CustomerResponse.NO_RESPONSE.value,
                        time_to_recovery_seconds=3600,
                        amount_paise=50_000_00,
                        recovered_paise=50_000_00 if succeeded else 0,
                        happiness_score=0.9 if succeeded else 0.5,
                        failure_reason=reason,
                        customer_segment="new",
                        region="west",
                        time_of_day="morning",
                    )
                )
        db.flush()

    async def test_log_attempt_persists_event(self, db):
        loop = FeedbackLoop()
        event = loop.log_attempt(
            db,
            recovery_id="rec_1",
            plan=_plan(),
            result=_result(success=True),
            payment_id="pay_fb_1",
            amount_paise=25_000_00,
            failure_reason="insufficient_funds",
            meta={"customer_segment": "retained", "region": "north", "support_tickets": "1"},
            payment_created_at=DT,
        )
        db.flush()
        assert event.customer_response == CustomerResponse.SUCCESS.value
        assert event.happiness_score == pytest.approx(0.85)
        assert event.time_of_day == "morning"

    async def test_weekly_aggregate_ranks_strategies(self, db):
        self._seed(
            db,
            [
                ("insufficient_funds", "nudge_digital", True, 8),
                ("insufficient_funds", "nudge_digital", False, 2),
                ("insufficient_funds", "smart_retry", True, 2),
                ("insufficient_funds", "smart_retry", False, 8),
            ],
        )
        agg = FeedbackLoop().weekly_aggregates(db, days=7, min_samples=5)

        assert agg["total_attempts"] == 20
        info = agg["by_failure_reason"]["insufficient_funds"]
        assert info["best_strategy"] == "SMS"
        rates = [(r["tactic"], r["success_rate"]) for r in info["ranking"]]
        assert rates == [("SMS", 0.8), ("retry", 0.2)]

    async def test_min_samples_filters_small_groups(self, db):
        self._seed(db, [("card_expired", "crm_human_escalation", True, 3)])
        agg = FeedbackLoop().weekly_aggregates(db, days=7, min_samples=5)
        info = agg["by_failure_reason"]["card_expired"]
        assert info["best_strategy"] is None
        assert info["ranking"] == []
        assert "escalate" in info["insufficient_data"]

    async def test_segment_region_time_dimensions(self, db):
        self._seed(
            db,
            [
                ("bank_decline", "high_touch_voice", True, 6),
            ],
        )
        # vary segment/region/time via direct updates
        for ev in db.execute(select(LearningEventRecord)).scalars():
            ev.customer_segment = "premium"
            ev.region = "south"
            ev.time_of_day = "night"
        db.flush()

        agg = FeedbackLoop().weekly_aggregates(db, days=7, min_samples=5)
        assert agg["by_customer_segment"]["premium"]["best_strategy"] == "call"
        assert agg["by_region"]["south"]["best_strategy"] == "call"
        assert agg["by_time_of_day"]["night"]["best_strategy"] == "call"

    async def test_dynamic_prompt_format(self, db):
        self._seed(
            db,
            [
                ("insufficient_funds", "nudge_digital", True, 72),
                ("insufficient_funds", "nudge_digital", False, 28),
                ("card_expired", "crm_human_escalation", True, 82),
                ("card_expired", "crm_human_escalation", False, 18),
            ],
        )
        agg = FeedbackLoop().weekly_aggregates(db, days=7, min_samples=5)
        prompt = FeedbackLoop().format_learning_prompt(agg)

        assert prompt.startswith("Based on 200 recovery attempts this week:")
        assert "- For insufficient_funds: SMS (72% success)" in prompt
        assert "- For card_expired: escalate (82% success)" in prompt
        assert prompt.endswith("Prioritize high-success strategies in your recommendations.")

    async def test_empty_prompt_when_no_data(self, db):
        assert FeedbackLoop().format_learning_prompt({"total_attempts": 0, "by_failure_reason": {}}) == ""


class TestLearnedStrategyOverride:
    @pytest.mark.asyncio
    async def test_overrides_heuristic_when_margin_large(self, monkeypatch):
        from app.agents.strategist_agent import StrategistAgent
        from app.models.payment import CustomerInfo, FailureReason, PaymentMethod, PaymentStatus, PaymentTransaction
        from app.models.recovery import Retryability
        import app.ml.feedback as feedback_mod

        txn = PaymentTransaction(
            payment_id="pay_learn_1",
            order_id="order_learn_1",
            customer=CustomerInfo(name="A", email="a@x.com", phone="+919000000000"),
            amount_paise=500_000,
            method=PaymentMethod.CARD,
            status=PaymentStatus.FAILED,
            failure_reason=FailureReason.CARD_EXPIRED,
        )
        snapshot = {
            "total_attempts": 120,
            "by_failure_reason": {
                "card_expired": {
                    "best_strategy": "offer",
                    "ranking": [
                        {"strategy": "crm_human_escalation", "tactic": "escalate", "attempts": 40, "success_rate": 0.85},
                        {"strategy": "smart_retry", "tactic": "retry", "attempts": 40, "success_rate": 0.05},
                    ],
                    "insufficient_data": [],
                }
            },
        }

        async def fake_snapshot():
            return snapshot

        monkeypatch.setattr(feedback_mod, "get_learning_snapshot", fake_snapshot)

        agent = StrategistAgent()
        learned, note = await agent._learned_strategy_override(txn, RecoveryStrategy.SMART_RETRY)
        assert learned == RecoveryStrategy.CRM_HUMAN_ESCALATION
        assert "card_expired" in note and "85%" in note

    @pytest.mark.asyncio
    async def test_no_override_without_margin(self, monkeypatch):
        from app.agents.strategist_agent import StrategistAgent
        from app.models.payment import CustomerInfo, FailureReason, PaymentMethod, PaymentStatus, PaymentTransaction
        import app.ml.feedback as feedback_mod

        txn = PaymentTransaction(
            payment_id="pay_learn_2",
            order_id="order_learn_2",
            customer=CustomerInfo(name="B", email="b@x.com", phone="+919000000001"),
            amount_paise=100_000,
            method=PaymentMethod.UPI,
            status=PaymentStatus.FAILED,
            failure_reason=FailureReason.NETWORK_ERROR,
        )
        snapshot = {
            "total_attempts": 30,
            "by_failure_reason": {
                "network_error": {
                    "best_strategy": "call",
                    "ranking": [
                        {"strategy": "high_touch_voice", "tactic": "call", "attempts": 15, "success_rate": 0.55},
                    ],
                    "insufficient_data": [],
                }
            },
        }

        async def fake_snapshot():
            return snapshot

        monkeypatch.setattr(feedback_mod, "get_learning_snapshot", fake_snapshot)

        learned, note = await StrategistAgent()._learned_strategy_override(
            txn, RecoveryStrategy.SMART_RETRY
        )
        # 55% < 60% bar -> never overrides
        assert learned is None and note == ""


class TestLearningAPI:
    def test_weekly_endpoint_shape(self, client):
        resp = client.get("/api/v1/metrics/learning/weekly")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"aggregates", "learning_prompt"}
        assert body["learning_prompt"] == ""
        assert body["aggregates"]["total_attempts"] >= 0

    def test_execute_feeds_the_loop(self, client, ingested_payment):
        executed = client.post(
            "/api/v1/recovery/execute",
            json={"payment_id": ingested_payment["payment_id"], "dry_run": False},
        )
        assert executed.status_code == 200, executed.text

        Base.metadata.create_all(get_engine())
        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        session = factory()
        try:
            events = session.execute(select(LearningEventRecord)).scalars().all()
            assert len(events) >= 1, "execution must log a learning event"
            event = events[-1]
            assert event.payment_id == ingested_payment["payment_id"]
            assert event.customer_response in {r.value for r in CustomerResponse}
            assert event.strategy in {"smart_retry", "nudge_digital", "high_touch_voice", "crm_human_escalation"}
            assert event.time_to_recovery_seconds >= 0
            assert 0.0 <= event.happiness_score <= 1.0
        finally:
            session.close()

    def test_dry_run_does_not_feed_the_loop(self, client, ingested_payment):
        executed = client.post(
            "/api/v1/recovery/execute",
            json={"payment_id": ingested_payment["payment_id"], "dry_run": True},
        )
        assert executed.status_code == 200, executed.text

        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        session = factory()
        try:
            count = len(session.execute(select(LearningEventRecord)).scalars().all())
            assert count == 0, "dry runs must not create learning events"
        finally:
            session.close()
