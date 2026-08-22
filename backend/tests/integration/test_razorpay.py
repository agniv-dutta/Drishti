"""Razorpay client integration tests.

Mock-mode behaviour is always tested; live test-mode API calls are skipped
unless RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are present in the environment.
"""

import pytest

from app.core.config import get_settings
from app.integrations.razorpay_client import RazorpayClient, get_razorpay_client


@pytest.fixture()
def rzp() -> RazorpayClient:
    # Reset the singleton so the client reflects current env (mock vs live).
    import app.integrations.razorpay_client as module

    module._razorpay_client = None
    return get_razorpay_client()


class TestMockMode:
    def test_mock_mode_when_no_credentials(self, rzp):
        if get_settings().razorpay_configured:
            pytest.skip("real credentials configured - mock path not active")
        assert rzp.mock_mode is True

    async def test_retry_creates_link_in_mock_mode(self, rzp):
        result = await rzp.retry_payment(
            gateway_payment_id="pay_test123",
            amount_paise=150000,
            customer_name="Test User",
            customer_email="t@example.com",
            customer_phone="+919876543210",
            reference_id="internal-1",
        )
        assert result.success is True
        assert result.reference and result.reference.startswith("plink_mock")
        assert result.raw["mock"] is True

    async def test_fetch_payment_mock(self, rzp):
        payment = await rzp.fetch_payment("pay_abc", amount_paise=10000)
        assert payment["_mock"] is True
        assert payment["amount"] == 10000


class TestWebhookSignature:
    @staticmethod
    def _client_with_secret(secret: str) -> RazorpayClient:
        from types import SimpleNamespace

        client = RazorpayClient()
        client._settings = SimpleNamespace(
            razorpay_webhook_secret=secret,
            razorpay_base_url="https://api.razorpay.com/v1",
            razorpay_key_id="k",
            razorpay_key_secret="s",
        )
        return client

    def test_bad_signature_rejected(self):
        client = self._client_with_secret("test-webhook-secret")
        assert client.verify_webhook_signature(b"{}", "deadbeef") is False

    def test_missing_secret_rejects_everything(self):
        client = self._client_with_secret(None)
        assert client.verify_webhook_signature(b"{}", "") is False

    def test_valid_signature_accepted(self):
        import hashlib
        import hmac

        secret = "test-webhook-secret"
        body = b'{"event": "payment.captured"}'
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        client = self._client_with_secret(secret)
        assert client.verify_webhook_signature(body, signature) is True
