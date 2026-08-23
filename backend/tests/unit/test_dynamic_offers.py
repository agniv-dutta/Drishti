import pytest

from app.agents.strategist_agent import StrategistAgent
from app.models.payment import CustomerInfo, FailureReason, PaymentTransaction
from app.models.recovery import FailureAnalysis, RecoveryStrategy, Retryability


def make_txn(amount_inr: float, **meta: str) -> PaymentTransaction:
    return PaymentTransaction(
        payment_id="pay_offer_1",
        customer=CustomerInfo(name="Test User", email="test@example.com", phone="+919876543210"),
        amount_paise=int(amount_inr * 100),
        failure_reason=FailureReason.BANK_DECLINE,
        meta={"customer_segment": "professional", **meta},
    )


def make_analysis() -> FailureAnalysis:
    return FailureAnalysis(
        payment_id="pay_offer_1",
        root_cause=FailureReason.BANK_DECLINE,
        retryability=Retryability.CUSTOMER_ACTION_REQUIRED,
        confidence=0.9,
        risk_score=0.7,
        risk_band="high",
    )


@pytest.mark.asyncio
async def test_offer_matches_competitor_with_twenty_percent_cap(monkeypatch):
    async def fetch_price(self, metadata):
        return 499.0

    monkeypatch.setattr(
        "app.agents.strategist_agent.get_competitor_pricing_client",
        lambda: type("Client", (), {"fetch_price": fetch_price})(),
    )
    plan = await StrategistAgent().run(
        make_txn(599, product_cost_inr="400"), make_analysis(), RecoveryStrategy.OFFER
    )

    assert plan.strategy == RecoveryStrategy.OFFER
    assert plan.discount_inr == 100
    assert plan.offer_price_inr == 499
    assert "₹499" in plan.offer_message


@pytest.mark.asyncio
async def test_offer_does_not_cross_product_cost(monkeypatch):
    async def fetch_price(self, metadata):
        return 499.0

    monkeypatch.setattr(
        "app.agents.strategist_agent.get_competitor_pricing_client",
        lambda: type("Client", (), {"fetch_price": fetch_price})(),
    )
    plan = await StrategistAgent().run(
        make_txn(599, product_cost_inr="550"), make_analysis(), RecoveryStrategy.OFFER
    )

    assert plan.discount_inr == 0
    assert plan.offer_price_inr is None
    assert plan.steps == []


@pytest.mark.asyncio
async def test_large_discount_escalates_to_human(monkeypatch):
    async def fetch_price(self, metadata):
        return 1000.0

    monkeypatch.setattr(
        "app.agents.strategist_agent.get_competitor_pricing_client",
        lambda: type("Client", (), {"fetch_price": fetch_price})(),
    )
    plan = await StrategistAgent().run(
        make_txn(10000, product_cost_inr="500"), make_analysis(), RecoveryStrategy.OFFER
    )

    assert plan.strategy == RecoveryStrategy.CRM_HUMAN_ESCALATION
    assert plan.requires_human_review is True
    assert plan.discount_inr == 0