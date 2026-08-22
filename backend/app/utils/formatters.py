"""Presentation helpers: INR formatting, masking, API response envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.models.payment import utcnow


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def _indian_grouping(digits: str) -> str:
    """Group digits Indian style: 1234567 -> 12,34,567."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def rupees_to_paise(amount_inr: float) -> int:
    return int(round(float(amount_inr) * 100))


def paise_to_rupees(amount_paise: int | float) -> float:
    return round(float(amount_paise) / 100.0, 2)


def format_inr(amount_inr: float, decimals: bool = True) -> str:
    """Rs 12,34,567.89 - Indian digit grouping."""
    negative = amount_inr < 0
    amount = abs(float(amount_inr))
    whole = int(amount)
    fraction = amount - whole
    grouped = _indian_grouping(str(whole))
    text = f"\u20b9{grouped}" + (f".{int(round(fraction * 100)):02d}" if decimals else "")
    return f"-{text}" if negative else text


def format_compact_inr(amount_inr: float) -> str:
    """Human-friendly lakh/crore notation for dashboards."""
    value = abs(amount_inr)
    sign = "-" if amount_inr < 0 else ""
    if value >= 1_00_00_000:
        return f"{sign}\u20b9{value / 1_00_00_000:.2f}Cr"
    if value >= 1_00_000:
        return f"{sign}\u20b9{value / 1_00_000:.2f}L"
    if value >= 1_000:
        return f"{sign}\u20b9{value / 1_000:.1f}K"
    return f"{sign}\u20b9{value:.2f}"


# ---------------------------------------------------------------------------
# Masking (PII-safe display)
# ---------------------------------------------------------------------------

def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())[-10:]
    return f"+91•••••{digits[-3:]}" if len(digits) == 10 else "••••"


def mask_email(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "•••"
    shown = local[:2] if len(local) > 2 else local[0]
    return f"{shown}•••@{domain}"


def mask_pan(pan: str) -> str:
    return f"{pan[:3]}•••••{pan[-2:]}" if pan and len(pan) >= 5 else "•••••"


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return utcnow().isoformat()


def humanize_minutes(minutes: int) -> str:
    if minutes <= 0:
        return "immediately"
    hours = minutes // 60
    days = hours // 24
    if days >= 1:
        return f"in {days} day{'s' if days != 1 else ''}"
    if hours >= 1:
        return f"in {hours} hour{'s' if hours != 1 else ''}"
    return f"in {minutes} minute{'s' if minutes != 1 else ''}"


def success_response(data: Any, message: str = "OK", **meta: Any) -> Dict[str, Any]:
    envelope: Dict[str, Any] = {"success": True, "message": message, "data": data}
    if meta:
        envelope["meta"] = meta
    return envelope


def error_response(
    code: str,
    message: str,
    details: Optional[Any] = None,
    **meta: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": False, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    if meta:
        payload["meta"] = meta
    return payload
