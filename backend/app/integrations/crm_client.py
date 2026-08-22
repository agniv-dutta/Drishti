"""CRM integration for human-in-the-loop escalation.

Generic webhook mode works with Zapier/Make/Freshsales/Salesforce Outbound
flows; provider-specific adapters can be added without touching agents.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings


@dataclass
class CRMResult:
    success: bool
    provider: str
    reference: Optional[str] = None
    detail: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


class BaseCRMProvider(ABC):
    name = "base"

    @abstractmethod
    async def push_event(self, event_type: str, payload: Dict[str, Any]) -> CRMResult: ...


class MockCRMProvider(BaseCRMProvider):
    name = "mock"

    async def push_event(self, event_type: str, payload: Dict[str, Any]) -> CRMResult:
        from app.core.logging_config import get_logger

        get_logger("drishti.crm").info("crm.mock_event", event_type=event_type, **payload)
        return CRMResult(True, self.name, f"mock-crm-{uuid.uuid4().hex[:10]}", "recorded (mock)")


class WebhookCRMProvider(BaseCRMProvider):
    """POST JSON to a generic endpoint (Zapier / Freshsales webhooks / SF middleware)."""

    name = "webhook"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.crm_webhook_url:
            raise RuntimeError("CRM_WEBHOOK_URL not configured")
        self._url = settings.crm_webhook_url
        self._api_key = settings.crm_api_key

    async def push_event(self, event_type: str, payload: Dict[str, Any]) -> CRMResult:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {"event_type": event_type, "source": "drishti", "data": payload}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self._url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            return CRMResult(False, self.name, detail=f"network error: {exc}")
        if 200 <= response.status_code < 300:
            return CRMResult(True, self.name, response.headers.get("x-request-id"))
        return CRMResult(False, self.name, detail=f"webhook error [{response.status_code}]: {response.text[:200]}")


def build_recovery_task(
    *,
    payment_id: str,
    customer_name: str,
    customer_email_masked: str,
    amount_inr: float,
    failure_reason: str,
    strategy: str,
    risk_score: float,
) -> Dict[str, Any]:
    """Payload shape expected by downstream CRM task automation."""
    return {
        "subject": f"[Recovery-{strategy}] Follow up on failed payment {payment_id}",
        "customer_name": customer_name,
        "customer_email": customer_email_masked,
        "amount_inr": round(amount_inr, 2),
        "failure_reason": failure_reason,
        "risk_score": risk_score,
        "priority": "High" if risk_score >= 0.65 else "Normal",
        "due_in_hours": 24,
    }


_crm_provider: Optional[BaseCRMProvider] = None


def get_crm_provider() -> BaseCRMProvider:
    global _crm_provider
    if _crm_provider is not None:
        return _crm_provider

    from app.core.logging_config import get_logger

    logger = get_logger("drishti.crm")
    choice = get_settings().crm_provider.lower()
    try:
        if choice in ("webhook", "salesforce", "freshsales"):
            # salesforce/freshsales route through the same outbound webhook today;
            # dedicated SDK adapters plug in here.
            _crm_provider = WebhookCRMProvider()
        else:
            _crm_provider = MockCRMProvider()
    except RuntimeError as exc:
        logger.warning("crm.provider_fallback_mock", requested=choice, error=str(exc))
        _crm_provider = MockCRMProvider()
    return _crm_provider
