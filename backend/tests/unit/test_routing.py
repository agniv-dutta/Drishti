"""Tests for confidence-based routing, human triage queue, and consent flow."""

from __future__ import annotations

import uuid
from datetime import timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.agents import get_supervisor
from app.database.models import (
    ConsentRequestRecord,
    PaymentRecord,
    utcnow,
)
from app.database.session import get_engine
from app.routing.confidence_router import (
    CONSENT_QUESTION,
    RoutingAction,
    RoutingDecision,
    classify_confidence,
    low_confidence_reasons,
    priority_score,
)
from app.routing.triage_service import create_triage_ticket, list_open_tickets
from tests.unit.test_i18n import _txn as make_txn


# ---------------------------------------------------------------------------
# decision tree boundaries
# ---------------------------------------------------------------------------
class TestClassifyConfidence:
    @pytest.mark.parametrize("confidence,expected", [
        (0.86, RoutingAction.AUTO_EXECUTE),
        (0.851, RoutingAction.AUTO_EXECUTE),
        (0.85, RoutingAction.EXECUTE_MONITOR),   # > 85% required for full auto
        (0.71, RoutingAction.EXECUTE_MONITOR),
        (0.70, RoutingAction.ASK_CUSTOMER),      # 70-85 band is exclusive below
        (0.51, RoutingAction.ASK_CUSTOMER),
        (0.50, RoutingAction.HUMAN_ESCALATION),
        (0.20, RoutingAction.HUMAN_ESCALATION),
    ])
    def test_thresholds_match_spec(self, confidence, expected):
        assert classify_confidence(confidence) is expected


# ---------------------------------------------------------------------------
# low-confidence explanations + priority scoring
# ---------------------------------------------------------------------------
class TestReasonsAndPriority:
    def test_low_value_known_reason_new_customer(self):
        txn = make_txn({})
        reasons = low_confidence_reasons(txn, _plan())
        assert reasons == ["new_customer_no_history"]

    def test_high_value_flagged(self):
        txn = make_txn({})
        txn.amount_paise = 30_000_000  # ₹3,00,000
        reasons = low_confidence_reasons(txn, _plan())
        assert any(r.startswith("high_value_payment") for r in reasons)

    def test_ambiguous_failure_reason(self):
        txn = make_txn({})
        txn.failure_reason = None
        reasons = low_confidence_reasons(txn, _plan())
        assert "ambiguous_failure (no failure reason from gateway)" in reasons

    def test_vague_gateway_error(self):
        txn = make_txn({})
        txn.error_description = "Unknown error at HDFC"
        reasons = low_confidence_reasons(txn, _plan())
        assert "vague_gateway_error_description" in reasons

    def test_priority_amount_dominates_then_new_customer(self):
        high_amount = make_txn({})
        high_amount.amount_paise = 100_000_000  # ₹10L -> 100 pts (cap)
        low_amount = make_txn({})
        low_amount.amount_paise = 500_000       # ₹5k -> 5 pts
        assert priority_score(high_amount, True) == 100.0
        assert priority_score(low_amount, False) == 5.5

        mid_value = make_txn({})
        mid_value.amount_paise = 2_000_000      # ₹20k -> 20 pts
        assert priority_score(mid_value, False) == priority_score(mid_value, True) + 5


def _plan(confidence: float = 0.4):
    from app.models.recovery import RecoveryChannel, RecoveryPlan, RecoveryStep, RecoveryStrategy

    return RecoveryPlan(
        plan_id=f"plan_test_{uuid.uuid4().hex[:8]}",
        payment_id="pay_i18n_1",
        strategy=RecoveryStrategy.SMART_RETRY,
        steps=[RecoveryStep(sequence=1, channel=RecoveryChannel.GATEWAY_RETRY,
                            delay_minutes=60, estimated_cost_paise=5)],
        expected_success_probability=confidence,
        rationale="test",
    )


# ---------------------------------------------------------------------------
# triage ticket service
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    Base.metadata.create_all(get_engine())
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    yield session
    session.close()


from app.database.models import Base  # noqa: E402


def _seed_payment(db, amount_inr: int = 5000) -> PaymentRecord:
    from app.utils.encryption import encrypt_dict

    record = PaymentRecord(
        id=f"pay_triage_{uuid.uuid4().hex[:10]}",
        order_id=f"order_{uuid.uuid4().hex[:10]}",
        customer_name="Ravi Kumar",
        customer_email_masked="r***@example.com",
        customer_contact_encrypted=encrypt_dict({"email": "ravi@example.com", "phone": "+919812345678"}),
        amount_paise=int(amount_inr * 100),
        method="card",
        status="failed",
        failure_reason="insufficient_funds",
        attempt_number=1,
        meta={},
    )
    db.add(record)
    db.flush()
    return record


def _decision(action: RoutingAction) -> RoutingDecision:
    return RoutingDecision(
        action=action,
        confidence=0.3,
        reasons=["high_value_payment", "new_customer_no_history"],
        priority_score=42.0,
        monitor=False,
    )


class TestTriageService:
    def test_create_ticket_is_idempotent_per_payment(self, db):
        payment = _seed_payment(db)
        plan = _plan(0.3)
        t1 = create_triage_ticket(db, payment, plan, _decision(RoutingAction.HUMAN_ESCALATION))
        t2 = create_triage_ticket(db, payment, plan, _decision(RoutingAction.HUMAN_ESCALATION))
        db.flush()
        assert t1.id == t2.id
        assert t1.status == "open"
        assert t1.customer_history["total_payments"] >= 1

    def test_queue_orders_by_priority_then_age(self, db):
        low = _seed_payment(db, amount_inr=2000)   # ₹2k
        high = _seed_payment(db, amount_inr=200_000)  # ₹2L
        for payment in (low, high):
            create_triage_ticket(db, payment, _plan(0.3), _decision(RoutingAction.HUMAN_ESCALATION))
        db.flush()
        tickets = list_open_tickets(db)
        assert tickets[0].payment_id == high.id
        assert tickets[0].priority_score > tickets[1].priority_score


# ---------------------------------------------------------------------------
# API-level flow: plan -> route -> triage -> override -> audit
# ---------------------------------------------------------------------------
class TestRoutingAPI:
    def test_low_confidence_lands_in_queue_and_blocks_execution(
        self, client, ingested_payment, monkeypatch
    ):
        _force_plan_confidence(monkeypatch, 0.30)
        pid = ingested_payment["payment_id"]

        plan_resp = client.post("/api/v1/recovery/plan", json={"payment_id": pid})
        assert plan_resp.status_code == 200

        queue = client.get("/api/v1/triage/queue").json()
        match = [t for t in queue["tickets"] if t["payment_id"] == pid]
        assert len(match) == 1
        ticket = match[0]
        assert ticket["recommended_strategy"]
        assert ticket["low_confidence_reasons"]
        assert ticket["priority_score"] > 0
        assert "customer_history" in ticket

        exec_resp = client.post("/api/v1/recovery/execute", json={"payment_id": pid})
        assert exec_resp.status_code == 400
        assert "triage" in exec_resp.json()["detail"].lower()

    def test_agent_override_replans_strategy_and_message_then_executes(
        self, client, ingested_payment, monkeypatch
    ):
        _force_plan_confidence(monkeypatch, 0.30)
        pid = ingested_payment["payment_id"]
        client.post("/api/v1/recovery/plan", json={"payment_id": pid})
        ticket = _only_ticket(client, pid)

        resp = client.post(
            f"/api/v1/triage/{ticket['ticket_id']}/override",
            json={
                "strategy": "high_touch_voice",
                "custom_message": "Hi Ravi, this is Meera from support - let's fix your payment together.",
                "note": "customer prefers calls, VIP account",
                "agent": "meera@support",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["overridden_strategy"] == "high_touch_voice"
        assert body["custom_message_applied"] is True
        assert body["status"] == "resolved"
        assert body["new_plan_id"].startswith("plan_")

        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        with factory() as db:
            payment = db.get(PaymentRecord, pid)
            assert payment.meta["custom_message"].startswith("Hi Ravi")

        trail = client.get("/api/v1/audit/trail?limit=50").json()
        events = trail.get("events") or trail.get("entries") or []
        assert any(
            e["event_type"] == "triage_override" and e["outcome"] == "escalated_by_agent"
            for e in events
        )

        # override replan cleared routing - execution proceeds now
        exec_resp = client.post("/api/v1/recovery/execute", json={"payment_id": pid})
        assert exec_resp.status_code == 200, exec_resp.text

    def test_invalid_override_strategy_rejected(self, client, ingested_payment, monkeypatch):
        _force_plan_confidence(monkeypatch, 0.30)
        pid = ingested_payment["payment_id"]
        client.post("/api/v1/recovery/plan", json={"payment_id": pid})
        ticket = _only_ticket(client, pid)
        resp = client.post(
            f"/api/v1/triage/{ticket['ticket_id']}/override",
            json={"strategy": "carrier_pigeon"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# ask-customer consent flow (50-70% band)
# ---------------------------------------------------------------------------
class TestConsentFlow:
    def test_yes_connects_chatbot_no_defers_72h(self, client, ingested_payment, monkeypatch):
        _force_plan_confidence(monkeypatch, 0.60)
        pid = ingested_payment["payment_id"]
        client.post("/api/v1/recovery/plan", json={"payment_id": pid})

        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        with factory() as db:
            consent = db.query(ConsentRequestRecord).filter_by(payment_id=pid).first()
            assert consent is not None and consent.question == CONSENT_QUESTION

        exec_resp = client.post("/api/v1/recovery/execute", json={"payment_id": pid})
        assert exec_resp.status_code == 400
        assert "consent" in exec_resp.json()["detail"].lower()

        yes = client.post("/api/v1/triage/consent/respond", json={"payment_id": pid, "response": "yes"})
        assert yes.status_code == 200
        body = yes.json()
        assert body["status"] == "accepted"
        assert len(body["options"]) == 3
        assert body["chatbot_session"].startswith("chat_")

        # a second awaiting request answered NO -> deferred 72h
        with factory() as db:
            db.add(ConsentRequestRecord(payment_id=pid, question=CONSENT_QUESTION, status="awaiting"))
            db.commit()

        no = client.post("/api/v1/triage/consent/respond", json={"payment_id": pid, "response": "no"})
        assert no.status_code == 200
        assert no.json()["status"] == "declined"

        with factory() as db:
            row = (
                db.query(ConsentRequestRecord)
                .filter_by(payment_id=pid)
                .order_by(ConsentRequestRecord.requested_at.desc())
                .first()
            )
            assert row.deferred_until is not None
            deferred = row.deferred_until if row.deferred_until.tzinfo else row.deferred_until.replace(tzinfo=timezone.utc)
            assert deferred > utcnow() + timedelta(hours=71)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _only_ticket(client, payment_id: str) -> dict:
    queue = client.get("/api/v1/triage/queue").json()
    match = [t for t in queue["tickets"] if t["payment_id"] == payment_id]
    assert match, "expected one open triage ticket"
    return match[0]


def _force_plan_confidence(monkeypatch, confidence: float) -> None:
    """Make the strategist emit plans with a fixed success probability."""
    from app.agents.strategist_agent import StrategistAgent
    from app.models.recovery import RecoveryChannel, RecoveryPlan, RecoveryStep

    def _plan_for(txn, conf, strategy):
        return RecoveryPlan(
            plan_id=f"plan_{txn.payment_id}_{int(conf * 100)}_{uuid.uuid4().hex[:6]}",
            payment_id=txn.payment_id,
            strategy=strategy,
            steps=[RecoveryStep(sequence=1, channel=RecoveryChannel.GATEWAY_RETRY,
                                delay_minutes=60, estimated_cost_paise=5)],
            expected_success_probability=conf,
            rationale=f"forced confidence {conf}",
        )

    async def fake_run(self, txn, analysis, override_strategy=None):
        return _plan_for(txn, confidence, override_strategy or strategy_for(txn))

    async def fake_run_from_consensus(self, txn, analysis, decision):
        winner = getattr(decision, "winner", None)
        strategy = getattr(winner, "strategy", None) or strategy_for(txn)
        return _plan_for(txn, confidence, strategy)

    def strategy_for(txn):
        from app.models.recovery import RecoveryStrategy

        return RecoveryStrategy.SMART_RETRY

    monkeypatch.setattr(StrategistAgent, "run", fake_run)
    monkeypatch.setattr(StrategistAgent, "run_from_consensus", fake_run_from_consensus)

