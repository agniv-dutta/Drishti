"""Razorpay test-mode integration (async httpx).

In live mode we follow the standard recovery pattern: failed payments are not
re-charged directly; instead a Payment Link is created against the original
amount and sent to the customer. In mock mode everything succeeds locally so
the agent pipeline is testable without credentials.
"""

from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class RazorpayError(RuntimeError):
    pass


class RazorpayAuthenticationError(RazorpayError):
    pass


class RazorpayRateLimitError(RazorpayError):
    pass


class RazorpayServerError(RazorpayError):
    pass


@dataclass
class GatewayResult:
    success: bool
    reference: Optional[str] = None
    detail: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


class RazorpayClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self.mock_mode = not self._settings.razorpay_configured

    @staticmethod
    def _mask(value: Any) -> Any:
        """Redact credentials and payment-card data before logging."""
        sensitive = {"authorization", "card", "card_number", "cvv", "number", "token", "secret"}
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if key.lower() in sensitive else RazorpayClient._mask(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [RazorpayClient._mask(item) for item in value]
        return value

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a Razorpay request, retrying transient failures 1s, 2s, 4s."""
        url = f"{self._settings.razorpay_base_url.rstrip('/')}/{path.lstrip('/')}"
        for attempt, delay in enumerate((0, 1, 2, 4)):
            if delay:
                await asyncio.sleep(delay)
            logger.info(
                "razorpay.request",
                extra={"method": method, "url": url, "request": self._mask(json or {})},
            )
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.request(
                        method, url, headers=self._auth_header, json=json
                    )
            except httpx.HTTPError as exc:
                if attempt < 3:
                    continue
                raise RazorpayServerError(f"Razorpay network error: {exc}") from exc

            try:
                body = response.json()
            except ValueError:
                body = {"detail": response.text[:500]}
            logger.info(
                "razorpay.response",
                extra={
                    "method": method,
                    "url": url,
                    "status_code": response.status_code,
                    "response": self._mask(body),
                },
            )
            if response.status_code in (401, 403):
                raise RazorpayAuthenticationError("Razorpay authentication failed")
            if response.status_code == 429:
                if attempt < 3:
                    continue
                raise RazorpayRateLimitError("Razorpay rate limit exceeded")
            if response.status_code >= 500:
                if attempt < 3:
                    continue
                raise RazorpayServerError(f"Razorpay server error [{response.status_code}]")
            if response.status_code >= 400:
                raise RazorpayError(f"Razorpay request failed [{response.status_code}]")
            return body
        raise RazorpayServerError("Razorpay request failed after retries")

    # ------------------------------------------------------------------
    @property
    def _auth_header(self) -> Dict[str, str]:
        key_id, key_secret = getattr(
            self._settings,
            "razorpay_key_pair",
            (self._settings.razorpay_key_id, self._settings.razorpay_key_secret),
        )
        credentials = f"{key_id}:{key_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

    @staticmethod
    def _mock_payment(payment_id: str, amount_paise: int) -> Dict[str, Any]:
        return {
            "id": payment_id,
            "status": "failed",
            "amount": amount_paise,
            "currency": "INR",
            "error_description": "mock_mode",
            "_mock": True,
        }

    # ------------------------------------------------------------------
    async def fetch_payment(self, gateway_payment_id: str, amount_paise: int = 0) -> Dict[str, Any]:
        """GET /payments/{id}. Returns synthetic payload in mock mode."""
        if self.mock_mode:
            return self._mock_payment(gateway_payment_id, amount_paise)

        return await self._request("GET", f"payments/{gateway_payment_id}")

    async def refund_payment(
        self,
        gateway_payment_id: str,
        amount_paise: Optional[int] = None,
        notes: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Issue a full or partial refund after recovery fails."""
        if self.mock_mode:
            return {
                "id": f"rfnd_mock_{uuid.uuid4().hex[:12]}",
                "payment_id": gateway_payment_id,
                "amount": amount_paise or 0,
                "status": "processed",
                "_mock": True,
            }
        payload: Dict[str, Any] = {}
        if amount_paise is not None:
            payload["amount"] = amount_paise
        if notes:
            payload["notes"] = notes
        return await self._request("POST", f"payments/{gateway_payment_id}/refund", json=payload)

    async def fetch_customer(self, customer_id: str) -> Dict[str, Any]:
        """Fetch a Razorpay customer profile."""
        if self.mock_mode:
            return {"id": customer_id, "name": "Test Customer", "email": "test@example.com", "_mock": True}
        return await self._request("GET", f"customers/{customer_id}")

    async def update_customer(self, customer_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update allowed Razorpay customer contact fields."""
        if self.mock_mode:
            return {"id": customer_id, **self._mask(updates), "_mock": True}
        return await self._request("PUT", f"customers/{customer_id}", json=updates)

    async def create_payment_link(
        self,
        *,
        amount_paise: int,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        reference_id: str,
        description: str = "Complete your pending payment",
    ) -> GatewayResult:
        """POST /payment_links - the recovery re-charge vehicle."""
        if self.mock_mode:
            link_id = f"plink_mock_{uuid.uuid4().hex[:12]}"
            return GatewayResult(
                success=True,
                reference=link_id,
                detail="mock payment link created",
                raw={
                    "id": link_id,
                    "short_url": f"https://rzp.io/i/{link_id[-8:]}",
                    "amount": amount_paise,
                    "reference_id": reference_id,
                    "mock": True,
                },
            )

        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "reference_id": reference_id,
            "description": description,
            "customer": {
                "name": customer_name,
                "email": customer_email,
                "contact": customer_phone,
            },
            "notify": {"sms": True, "email": True},
            "reminder_enable": True,
        }
        try:
            body = await self._request("POST", "payment_links", json=payload)
            return GatewayResult(success=True, reference=body.get("id"), raw=body)
        except RazorpayError as exc:
            return GatewayResult(success=False, detail=str(exc))

    async def retry_payment(
        self,
        gateway_payment_id: str,
        amount_paise: int,
        customer_name: str = "",
        customer_email: str = "",
        customer_phone: str = "",
        reference_id: str = "",
    ) -> GatewayResult:
        """Recovery charge = fresh payment link tied to the original payment."""
        return await self.create_payment_link(
            amount_paise=amount_paise,
            customer_name=customer_name or "Customer",
            customer_email=customer_email or "unknown@example.com",
            customer_phone=customer_phone or "+910000000000",
            reference_id=reference_id or gateway_payment_id,
            description=f"Retry for payment {gateway_payment_id}",
        )

    # ------------------------------------------------------------------
    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        secret = self._settings.razorpay_webhook_secret
        if not secret:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


_razorpay_client: Optional[RazorpayClient] = None


def get_razorpay_client() -> RazorpayClient:
    global _razorpay_client
    if _razorpay_client is None:
        _razorpay_client = RazorpayClient()
    return _razorpay_client
