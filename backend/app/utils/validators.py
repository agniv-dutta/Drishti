"""Input validation helpers (PAN, email, phone, UPI VPA) with normalization."""

from __future__ import annotations

import re
from typing import Optional


class InvalidInputError(ValueError):
    """Raised when an input fails validation; safe to surface to API callers."""


# Indian PAN: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Indian mobile numbers: optional +91 / 91 / 0 prefix, then 6-9 start digit.
_PHONE_RE = re.compile(r"^(?:\+?91[-\s]?|0)?([6-9]\d{9})$")

# Conservative email pattern; EmailStr handles schema-level validation too.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)

# UPI VPA: name@psp (e.g. agniv@okhdfcbank)
_UPI_VPA_RE = re.compile(r"^[a-zA-Z0-9.\-_]{2,64}@[a-zA-Z]{2,32}$")


def is_valid_pan(pan: str) -> bool:
    return bool(_PAN_RE.match((pan or "").strip().upper()))


def validate_pan(pan: str) -> str:
    normalized = (pan or "").strip().upper()
    if not _PAN_RE.match(normalized):
        raise InvalidInputError(f"Invalid PAN format: expected AAAAA9999A, got '{pan}'")
    return normalized


def normalize_indian_phone(phone: str) -> str:
    """Return E.164 form ``+91XXXXXXXXXX`` or raise InvalidInputError."""
    cleaned = re.sub(r"[\s\-().]", "", (phone or "").strip())
    match = _PHONE_RE.match(cleaned)
    if not match:
        raise InvalidInputError(f"Invalid Indian mobile number: '{phone}'")
    return f"+91{match.group(1)}"


def is_valid_indian_phone(phone: str) -> bool:
    try:
        normalize_indian_phone(phone)
        return True
    except InvalidInputError:
        return False


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def validate_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise InvalidInputError(f"Invalid email address: '{email}'")
    return normalized


def is_valid_upi_vpa(vpa: str) -> bool:
    return bool(_UPI_VPA_RE.match((vpa or "").strip()))


def luhn_check(card_number: str) -> bool:
    """Standard Luhn checksum for card-like identifiers."""
    digits = re.sub(r"[\s-]", "", card_number or "")
    if not digits.isdigit() or len(digits) < 12:
        return False
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def validate_amount_paise(amount_paise: int) -> int:
    if not isinstance(amount_paise, int) or amount_paise <= 0:
        raise InvalidInputError("amount must be a positive integer number of paise")
    if amount_paise > 1_000_000_000_00:  # Rs 100 crore sanity ceiling
        raise InvalidInputError("amount exceeds maximum supported transaction size")
    return amount_paise


def sanitize_text(value: Optional[str], max_length: int = 512) -> str:
    """Strip control characters and clamp length for log-safe storage."""
    if value is None:
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))
    return cleaned.strip()[:max_length]
