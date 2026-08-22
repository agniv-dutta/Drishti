"""SMS delivery: Twilio, AWS SNS, or an offline mock.

Provider selection comes from settings (``SMS_PROVIDER``); misconfiguration
degrades to the mock with a warning rather than breaking recovery runs.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import get_settings


@dataclass
class MessageResult:
    success: bool
    provider: str
    reference: Optional[str] = None
    detail: str = ""


class BaseSMSProvider(ABC):
    name = "base"

    @abstractmethod
    async def send(self, to_e164: str, message: str) -> MessageResult: ...


class MockSMSProvider(BaseSMSProvider):
    """Logs the message; always succeeds. For dev/test."""

    name = "mock"

    async def send(self, to_e164: str, message: str) -> MessageResult:
        from app.core.logging_config import get_logger

        get_logger("drishti.sms").info("sms.mock_sent", to=to_e164, body=message)
        return MessageResult(True, self.name, f"mock-sms-{uuid.uuid4().hex[:10]}", "delivered (mock)")


class TwilioProvider(BaseSMSProvider):
    name = "twilio"

    def __init__(self) -> None:
        settings = get_settings()
        if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
            raise RuntimeError("Twilio credentials incomplete (TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER)")
        self._sid = settings.twilio_account_sid
        self._token = settings.twilio_auth_token
        self._from = settings.twilio_from_number

    async def send(self, to_e164: str, message: str) -> MessageResult:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    auth=(self._sid, self._token),
                    data={"To": to_e164, "From": self._from, "Body": message},
                )
        except httpx.HTTPError as exc:
            return MessageResult(False, self.name, detail=f"network error: {exc}")
        if response.status_code in (200, 201):
            return MessageResult(True, self.name, response.json().get("sid"))
        return MessageResult(False, self.name, detail=f"twilio error [{response.status_code}]: {response.text[:200]}")


class SNSProvider(BaseSMSProvider):
    """AWS SNS transactional SMS via boto3 (optional dependency)."""

    name = "sns"

    def __init__(self) -> None:
        try:
            import boto3  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("boto3 not installed - pip install boto3 for SNS support") from exc

    async def send(self, to_e164: str, message: str) -> MessageResult:
        import asyncio

        import boto3

        settings = get_settings()
        sns = boto3.client("sns", region_name=settings.aws_region)

        def _publish() -> dict:
            return sns.publish(
                PhoneNumber=to_e164,
                Message=message,
                MessageAttributes={
                    "AWS.SNS.SMS.SenderID": {
                        "DataType": "String",
                        "StringValue": settings.sns_sender_id,
                    },
                    "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
                },
            )

        try:
            response = await asyncio.to_thread(_publish)
            return MessageResult(True, self.name, response.get("MessageId"))
        except Exception as exc:  # noqa: BLE001
            return MessageResult(False, self.name, detail=str(exc))


# ---------------------------------------------------------------------------
# Templates (DLT-style registered content)
# ---------------------------------------------------------------------------

def build_recovery_sms(
    customer_name: str,
    amount_str: str,
    merchant: str = "your merchant",
    payment_link: Optional[str] = None,
) -> str:
    first_name = customer_name.split(" ")[0]
    base = (
        f"Hi {first_name}, your payment of {amount_str} to {merchant} could not be processed. "
    )
    if payment_link:
        base += f"Complete it securely here: {payment_link}"
    else:
        base += "Retry anytime from your app."
    return base + " Reply STOP to opt out."


_sms_provider: Optional[BaseSMSProvider] = None


def get_sms_provider() -> BaseSMSProvider:
    global _sms_provider
    if _sms_provider is not None:
        return _sms_provider

    from app.core.logging_config import get_logger

    logger = get_logger("drishti.sms")
    choice = get_settings().sms_provider.lower()
    try:
        if choice == "twilio":
            _sms_provider = TwilioProvider()
        elif choice == "sns":
            _sms_provider = SNSProvider()
        else:
            _sms_provider = MockSMSProvider()
    except RuntimeError as exc:
        logger.warning("sms.provider_fallback_mock", requested=choice, error=str(exc))
        _sms_provider = MockSMSProvider()
    return _sms_provider
