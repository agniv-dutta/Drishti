"""Focused encryption and privacy regression tests."""

import pytest
from cryptography.fernet import InvalidToken

from app.utils.encryption import decrypt_dict, decrypt_str, encrypt_dict, encrypt_str


def test_encrypt_decrypt_string_roundtrip():
    token = encrypt_str("sensitive payment contact")
    assert token != "sensitive payment contact"
    assert decrypt_str(token) == "sensitive payment contact"


def test_encrypt_decrypt_dict_preserves_types():
    payload = {"email": "customer@example.com", "attempts": 3, "active": True}
    assert decrypt_dict(encrypt_dict(payload)) == payload


def test_modified_ciphertext_is_rejected():
    token = encrypt_str("do not alter")
    with pytest.raises(InvalidToken):
        decrypt_str(token[:-1] + ("A" if token[-1] != "A" else "B"))
