"""Unit tests for input validators."""

import pytest

from app.utils.validators import (
    InvalidInputError,
    is_valid_email,
    is_valid_indian_phone,
    is_valid_pan,
    is_valid_upi_vpa,
    luhn_check,
    normalize_indian_phone,
    sanitize_text,
    validate_amount_paise,
    validate_pan,
)


class TestPan:
    def test_valid_pan(self):
        assert is_valid_pan("ABCDE1234F")
        assert validate_pan(" abcde1234f ") == "ABCDE1234F"

    def test_invalid_pans(self):
        for bad in ["ABCD1234F", "ABCDE1234FF", "1234512345", "ABCDE@234F", ""]:
            assert not is_valid_pan(bad)
        with pytest.raises(InvalidInputError):
            validate_pan("nope")


class TestPhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("9876543210", "+919876543210"),
            ("+91 98765 43210", "+919876543210"),
            ("09876543210", "+919876543210"),
            ("919876543210", "+919876543210"),
        ],
    )
    def test_normalization(self, raw, expected):
        assert normalize_indian_phone(raw) == expected

    def test_rejects_landline_and_garbage(self):
        for bad in ["12345", "5123456789", "not-a-phone", "+4412345678901"]:
            with pytest.raises(InvalidInputError):
                normalize_indian_phone(bad)

    def test_is_valid_helper(self):
        assert is_valid_indian_phone("7894561230")
        assert not is_valid_indian_phone("0000000000")


class TestEmailAndUpi:
    def test_emails(self):
        assert is_valid_email("user.name+tag@domain.co.in")
        assert not is_valid_email("missing-at-sign.com")

    def test_upi_vpa(self):
        assert is_valid_upi_vpa("agniv@okhdfcbank")
        assert not is_valid_upi_vpa("@bad")


class TestMisc:
    def test_luhn(self):
        # 4111111111111111 is the classic Luhn-valid test card
        assert luhn_check("4111111111111111")
        assert not luhn_check("4111111111111112")

    def test_amount_validation(self):
        assert validate_amount_paise(100) == 100
        with pytest.raises(InvalidInputError):
            validate_amount_paise(0)
        with pytest.raises(InvalidInputError):
            validate_amount_paise(-5)

    def test_sanitize_strips_control_chars(self):
        assert sanitize_text("hello\x00\x08world") == "helloworld"
        assert sanitize_text(None) == ""
