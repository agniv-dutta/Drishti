"""Integration-style tests for the Razorpay client using HTTP doubles."""

from types import SimpleNamespace

import httpx
import pytest

from app.integrations.razorpay_client import (
    RazorpayAuthenticationError,
    RazorpayClient,
    RazorpayRateLimitError,
    RazorpayServerError,
)


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class FakeAsyncClient:
    responses = []
    calls = []

    def __init__(self, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, headers, json=None):
        self.calls.append((method, url, json))
        return self.responses.pop(0)


def live_client():
    client = RazorpayClient()
    client.mock_mode = False
    client._settings = SimpleNamespace(
        razorpay_base_url="https://api.razorpay.com/v1",
        razorpay_key_id="rzp_test_key",
        razorpay_key_secret="test_secret",
        razorpay_key_pair=("rzp_test_key", "test_secret"),
    )
    return client


@pytest.mark.asyncio
async def test_mock_payment_and_customer_operations():
    client = RazorpayClient()
    payment = await client.fetch_payment("pay_test", 5000)
    refund = await client.refund_payment("pay_test", 5000)
    customer = await client.fetch_customer("cust_test")

    assert payment["_mock"] is True
    assert refund["_mock"] is True
    assert customer["_mock"] is True


@pytest.mark.asyncio
async def test_transient_server_error_retries_three_times(monkeypatch):
    FakeAsyncClient.responses = [
        FakeResponse(500, {"error": "temporary"}),
        FakeResponse(500, {"error": "temporary"}),
        FakeResponse(500, {"error": "temporary"}),
        FakeResponse(200, {"id": "pay_test", "status": "captured"}),
    ]
    FakeAsyncClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.integrations.razorpay_client.asyncio.sleep", lambda _: noop())

    async def noop():
        return None

    payment = await live_client().fetch_payment("pay_test")
    assert payment["status"] == "captured"
    assert len(FakeAsyncClient.calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,exception",
    [(401, RazorpayAuthenticationError), (429, RazorpayRateLimitError), (503, RazorpayServerError)],
)
async def test_gateway_errors_are_typed(monkeypatch, status, exception):
    FakeAsyncClient.responses = [FakeResponse(status, {"error": "failed"})] * 4
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.integrations.razorpay_client.asyncio.sleep", lambda _: _noop())

    async def _noop():
        return None

    with pytest.raises(exception):
        await live_client().fetch_payment("pay_test")


@pytest.mark.asyncio
async def test_refund_and_customer_update_use_expected_endpoints(monkeypatch):
    FakeAsyncClient.responses = [
        FakeResponse(200, {"id": "rfnd_1"}),
        FakeResponse(200, {"id": "cust_1", "email": "new@example.com"}),
    ]
    FakeAsyncClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = live_client()

    await client.refund_payment("pay_1", 1000)
    await client.update_customer("cust_1", {"email": "new@example.com"})

    assert FakeAsyncClient.calls[0][0:2] == ("POST", "https://api.razorpay.com/v1/payments/pay_1/refund")
    assert FakeAsyncClient.calls[1][0:2] == ("PUT", "https://api.razorpay.com/v1/customers/cust_1")
