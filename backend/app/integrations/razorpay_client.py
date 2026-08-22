"""Razorpay test-mode integration (async httpx).

In live mode we follow the standard recovery pattern: failed payments are not
re-charged directly; instead a Payment Link is created against the original
amount and sent to the customer. In mock mode everything succeeds locally so
the agent pipeline is testable without credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings


class RazorpayError(RuntimeError):
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

    # ------------------------------------------------------------------
    @property
    def _auth_header(self) -> Dict[str, str]:
        credentials = f"{self._settings.razorpay_key_id}:{self._settings.razorpay_key_secret}"
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

        url = f"{self._settings.razorpay_base_url}/payments/{gateway_payment_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=self._auth_header)
        if response.status_code != 200:
            raise RazorpayError(f"fetch_payment failed [{response.status_code}]: {response.text}")
        return response.json()

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
        url = f"{self._settings.razorpay_base_url}/payment_links"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=self._auth_header, json=payload)
        except httpx.HTTPError as exc:
            return GatewayResult(success=False, detail=f"network error: {exc}")
        if response.status_code in (200, 201):
            body = response.json()
            return GatewayResult(success=True, reference=body.get("id"), raw=body)
        return GatewayResult(
            success=False,
            detail=f"payment link rejected [{response.status_code}]: {response.text[:300]}",
            raw=response.json() if response.headers.get("content-type", "").startswith("application/json") else {},
        )

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
