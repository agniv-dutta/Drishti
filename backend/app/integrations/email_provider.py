"""Email delivery: SendGrid, AWS SES, or an offline mock."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.core.config import get_settings


@dataclass
class EmailContent:
    subject: str
    plain: str
    html: str = field(default="")


@dataclass
class EmailResult:
    success: bool
    provider: str
    reference: Optional[str] = None
    detail: str = ""


class BaseEmailProvider(ABC):
    name = "base"

    @abstractmethod
    async def send(self, to_email: str, content: EmailContent) -> EmailResult: ...


class MockEmailProvider(BaseEmailProvider):
    name = "mock"

    async def send(self, to_email: str, content: EmailContent) -> EmailResult:
        from app.core.logging_config import get_logger

        get_logger("drishti.email").info(
            "email.mock_sent", to=to_email, subject=content.subject
        )
        return EmailResult(
            True, self.name, f"mock-email-{uuid.uuid4().hex[:10]}", "delivered (mock)"
        )


class SendGridProvider(BaseEmailProvider):
    name = "sendgrid"
    API_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.sendgrid_api_key:
            raise RuntimeError("SENDGRID_API_KEY not configured")
        self._api_key = settings.sendgrid_api_key
        self._from = settings.sendgrid_from_email

    async def send(self, to_email: str, content: EmailContent) -> EmailResult:
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": self._from},
            "subject": content.subject,
            "content": [
                {"type": "text/plain", "value": content.plain},
                *([{"type": "text/html", "value": content.html}] if content.html else []),
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            return EmailResult(False, self.name, detail=f"network error: {exc}")
        if response.status_code in (200, 202):
            return EmailResult(True, self.name, response.headers.get("X-Message-Id"))
        return EmailResult(False, self.name, detail=f"sendgrid error [{response.status_code}]: {response.text[:200]}")


class SESProvider(BaseEmailProvider):
    """AWS SES v2 via boto3 (optional dependency)."""

    name = "ses"

    def __init__(self) -> None:
        try:
            import boto3  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("boto3 not installed - pip install boto3 for SES support") from exc

    async def send(self, to_email: str, content: EmailContent) -> EmailResult:
        import asyncio

        import boto3

        settings = get_settings()
        ses = boto3.client("sesv2", region_name=settings.aws_region)

        def _send() -> dict:
            body: dict = {"Text": {"Data": content.plain}}
            if content.html:
                body["Html"] = {"Data": content.html}
            return ses.send_email(
                FromEmailAddress=settings.ses_from_email,
                Destination={"ToAddresses": [to_email]},
                Content={
                    "Simple": {
                        "Subject": {"Data": content.subject},
                        "Body": body,
                    }
                },
            )

        try:
            response = await asyncio.to_thread(_send)
            return EmailResult(True, self.name, response.get("MessageId"))
        except Exception as exc:  # noqa: BLE001
            return EmailResult(False, self.name, detail=str(exc))


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def build_recovery_email(
    customer_name: str,
    amount_str: str,
    merchant: str = "your merchant",
    payment_link: Optional[str] = None,
) -> EmailContent:
    first_name = customer_name.split(" ")[0]
    subject = f"Action needed: your payment of {amount_str} didn't go through"
    cta = (
        f'<a href="{payment_link}" style="background:#0ea5e9;color:#fff;padding:12px 24px;'
        'border-radius:6px;text-decoration:none">Complete Payment</a>'
        if payment_link
        else "Please retry from the app."
    )
    plain = (
        f"Hi {first_name},\n\nYour payment of {amount_str} to {merchant} failed.\n"
        f"{cta}\n\nIf you were charged, this amount will be auto-refunded in 5-7 days.\n\n"
        "- Team Drishti"
    )
    html = (
        f"<p>Hi {first_name},</p>"
        f"<p>Your payment of <b>{amount_str}</b> to {merchant} could not be processed.</p>"
        f"<p>{cta}</p>"
        "<p style='color:#888;font-size:12px'>You received this because a recent "
        "transaction was unsuccessful.</p>"
    )
    return EmailContent(subject=subject, plain=plain, html=html)


_email_provider: Optional[BaseEmailProvider] = None


def get_email_provider() -> BaseEmailProvider:
    global _email_provider
    if _email_provider is not None:
        return _email_provider

    from app.core.logging_config import get_logger

    logger = get_logger("drishti.email")
    choice = get_settings().email_provider.lower()
    try:
        if choice == "sendgrid":
            _email_provider = SendGridProvider()
        elif choice == "ses":
            _email_provider = SESProvider()
        else:
            _email_provider = MockEmailProvider()
    except RuntimeError as exc:
        logger.warning("email.provider_fallback_mock", requested=choice, error=str(exc))
        _email_provider = MockEmailProvider()
    return _email_provider
