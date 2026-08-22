"""Unit tests for encryption utilities and formatters."""

import pytest
from cryptography.fernet import InvalidToken

from app.utils.encryption import (
    decrypt_dict,
    decrypt_str,
    encrypt_dict,
    encrypt_str,
    pseudonymize,
    scrub_payload,
)
from app.utils.formatters import (
    format_compact_inr,
    format_inr,
    mask_email,
    mask_pan,
    mask_phone,
)


class TestEncryption:
    def test_string_roundtrip(self):
        token = encrypt_str("card 4111-1111")
        assert token != "card 4111-1111"
        assert decrypt_str(token) == "card 4111-1111"

    def test_dict_roundtrip(self):
        payload = {"email": "a@b.com", "phone": "+919876543210", "amount": 100}
        assert decrypt_dict(encrypt_dict(payload)) == payload

    def test_tampered_token_rejected(self):
        with pytest.raises(InvalidToken):
            decrypt_str(encrypt_str("secret")[:-4] + "AAAA")

    def test_scrub_masks_pii_and_encrypts_sensitive(self):
        cleaned = scrub_payload(
            {"email": "john.doe@example.com", "phone": "+919876543210", "cvv": "123", "note": "ok"}
        )
        assert cleaned["email"] != "john.doe@example.com"
        assert "@" in cleaned["email"]  # masked but readable shape
        assert cleaned["phone"].endswith("210")
        assert cleaned["cvv"] != "123"  # encrypted
        assert decrypt_str(cleaned["cvv"]) == "123"
        assert cleaned["note"] == "ok"

    def test_pseudonymize_deterministic(self):
        assert pseudonymize("user@example.com") == pseudonymize("User@Example.com")
        assert pseudonymize("a@x.com") != pseudonymize("b@x.com")


class TestFormatters:
    def test_indian_grouping(self):
        assert format_inr(1234567.89) == "\u20b912,34,567.89"
        assert format_inr(100) == "\u20b9100.00"
        assert format_inr(-500) == "-\u20b9500.00"

    def test_compact_notation(self):
        assert format_compact_inr(15_00_000) == "\u20b915.00L"
        assert format_compact_inr(2_50_00_000) == "\u20b92.50Cr"
        assert format_compact_inr(950) == "\u20b9950.00"

    def test_masks(self):
        assert mask_phone("+919876543210") == "+91\u2022\u2022\u2022\u2022\u2022210"
        assert mask_email("johndoe@example.com").startswith("jo")
        assert "\u2022" in mask_pan("ABCDE1234F")
