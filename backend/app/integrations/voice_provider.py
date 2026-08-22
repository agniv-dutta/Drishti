"""Voice / IVR outreach with Hinglish call scripts.

Scripts are generated in conversational Hinglish (Hindi-English mix) which
consistently outperforms English-only IVR for Indian payment recovery. Real
dialing is pluggable (Exotel shown); mock mode logs the script.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from app.core.config import get_settings


@dataclass
class IVRScript:
    lines: List[str] = field(default_factory=list)
    language: str = "hinglish"
    max_duration_seconds: int = 60

    def as_text(self) -> str:
        return "\n".join(self.lines)


def build_hinglish_script(
    customer_name: str,
    amount_str: str,
    merchant: str = "merchant",
    payment_link: Optional[str] = None,
) -> IVRScript:
    first_name = customer_name.split(" ")[0]
    link_line = (
        f"Link aapke phone par SMS mein bhej diya hai - wahan se turant payment kar sakte hain."
        if payment_link
        else "Aap apne app se kabhi bhi payment retry kar sakte hain."
    )
    return IVRScript(
        lines=[
            f"Namaste {first_name} ji! Main Drishti se bol rahi hoon.",
            f"Aapki {amount_str} ki payment {merchant} ko fail ho gayi thi.",
            "Kya aap abhi payment complete karna chahenge?",
            "Dabaiye ek agar haan, do agar aapko thoda time chahiye.",
            link_line,
            "Dhanyavaad! Aapka din shubh ho.",
        ]
    )


@dataclass
class CallResult:
    success: bool
    provider: str
    reference: Optional[str] = None
    detail: str = ""


class BaseVoiceProvider(ABC):
    name = "base"

    @abstractmethod
    async def place_call(self, to_e164: str, script: IVRScript) -> CallResult: ...


class MockVoiceProvider(BaseVoiceProvider):
    name = "mock"

    async def place_call(self, to_e164: str, script: IVRScript) -> CallResult:
        from app.core.logging_config import get_logger

        get_logger("drishti.voice").info(
            "ivr.mock_call", to=to_e164, script=script.as_text()
        )
        return CallResult(True, self.name, f"mock-call-{uuid.uuid4().hex[:10]}", "connected (mock)")


class ExotelProvider(BaseVoiceProvider):
    """Exotel outbound campaign call (App Bazaar flow)."""

    name = "exotel"
    API_URL = "https://{sid}:{token}@api.exotel.com/v1/Accounts/{sid}/Calls/connect.json"

    def __init__(self) -> None:
        settings = get_settings()
        if not (settings.exotel_api_key and settings.exotel_api_token and settings.exotel_from_number):
            raise RuntimeError("Exotel credentials incomplete (EXOTEL_API_KEY/API_TOKEN/FROM_NUMBER)")
        self._key = settings.exotel_api_key
        self._token = settings.exotel_api_token
        self._from = settings.exotel_from_number

    async def place_call(self, to_e164: str, script: IVRScript) -> CallResult:
        url = self.API_URL.format(sid=self._key, token=self._token)
        data = {
            "From": to_e164,
            "CallerId": self._from,
            "Url": "http://my.exotel.com/exoml/start_voice_app",  # App holding the TTS flow
            "CustomField": script.as_text()[:1000],
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, data=data)
        except httpx.HTTPError as exc:
            return CallResult(False, self.name, detail=f"network error: {exc}")
        if response.status_code in (200, 201):
            call = response.json().get("Call", {})
            return CallResult(True, self.name, call.get("Sid"))
        return CallResult(False, self.name, detail=f"exotel error [{response.status_code}]: {response.text[:200]}")


_voice_provider: Optional[BaseVoiceProvider] = None


def get_voice_provider() -> BaseVoiceProvider:
    global _voice_provider
    if _voice_provider is not None:
        return _voice_provider

    from app.core.logging_config import get_logger

    logger = get_logger("drishti.voice")
    choice = get_settings().voice_provider.lower()
    try:
        if choice == "exotel":
            _voice_provider = ExotelProvider()
        else:
            _voice_provider = MockVoiceProvider()
    except RuntimeError as exc:
        logger.warning("voice.provider_fallback_mock", requested=choice, error=str(exc))
        _voice_provider = MockVoiceProvider()
    return _voice_provider
