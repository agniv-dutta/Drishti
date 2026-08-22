"""Unit tests for synthetic data generation and the analyzer's rule engine."""

from app.agents.analyzer_agent import AnalyzerAgent, GATEWAY_CODE_MAP, RETRYABILITY_BY_REASON
from app.models.payment import FailureReason, PaymentTransaction, CustomerInfo, Retryability
from app.utils.mock_data import generate_payment_batch, make_failed_payment


class TestAnalyzer:
    def setup_method(self):
        self.agent = AnalyzerAgent()

    def _txn(self, code: str = "insufficient_funds", description: str = "") -> PaymentTransaction:
        return PaymentTransaction(
            payment_id="pay_test_1",
            order_id="order_test_1",
            customer=CustomerInfo(name="Test User", email="t@example.com", phone="+919876543210"),
            amount_paise=250000,
            method="card",
            status="failed",
            error_code=code,
            error_description=description,
        )

    async def test_maps_known_gateway_code(self):
        analysis = await self.agent.run(self._txn("insufficient_funds"))
        assert analysis.root_cause == FailureReason.INSUFFICIENT_FUNDS
        assert analysis.retryability == Retryability.DELAYED_RETRY
        assert analysis.confidence >= 0.85

    async def test_infers_from_free_text_description(self):
        analysis = await self.agent.run(
            self._txn("GATEWAY_ERR_X99", description="Card was declined by bank - do not honor")
        )
        assert analysis.root_cause == FailureReason.BANK_DECLINE

    async def test_unknown_stays_unknown_offline(self):
        analysis = await self.agent.run(self._txn("totally_novel_code_9000"))
        assert analysis.root_cause == FailureReason.UNKNOWN
        assert 0 < analysis.risk_score < 1

    def test_every_mapped_reason_has_retryability(self):
        for reason in GATEWAY_CODE_MAP.values():
            assert reason in RETRYABILITY_BY_REASON


class TestMockData:
    def test_batch_shape_and_validity(self):
        batch = generate_payment_batch(25, seed=7)
        assert len(batch) == 25
        failed = [p for p in batch if p["status"] == "failed"]
        assert failed, "expected at least one failed payment"
        for payment in batch:
            assert payment["amount"] > 0
            assert payment["customer"]["phone"].startswith("+91")

    def test_seeded_generation_is_deterministic(self):
        a = make_failed_payment(seed=42)
        b = make_failed_payment(seed=42)
        assert a["order_id"] == b["order_id"]
        assert a["customer"] == b["customer"]
