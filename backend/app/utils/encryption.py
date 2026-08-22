"""Field-level encryption for sensitive payment data (Fernet symmetric).

The key comes from settings (``ENCRYPTION_KEY``). If absent, an ephemeral key
is generated per-process - fine for local dev, but set a stable key outside
development or encrypted values will not be decryptable after restart.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.utils.formatters import mask_email, mask_phone

_lock = threading.Lock()
_fernet = None  # type: ignore[var-annotated]
_ephemeral_warned = False


def _get_fernet():
    global _fernet, _ephemeral_warned
    if _fernet is not None:
        return _fernet
    with _lock:
        if _fernet is not None:
            return _fernet
        from cryptography.fernet import Fernet

        settings = get_settings()
        key = settings.encryption_key
        if not key:
            if not _ephemeral_warned and not settings.is_production:
                import logging

                logging.getLogger(__name__).warning(
                    "ENCRYPTION_KEY not set; using ephemeral in-memory key "
                    "(encrypted values will NOT survive restarts)"
                )
                _ephemeral_warned = True
            key = Fernet.generate_key().decode()
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet


def encrypt_str(plaintext: str) -> str:
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_str(token: str) -> str:
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def encrypt_dict(payload: Dict[str, Any]) -> str:
    return encrypt_str(json.dumps(payload, default=str))


def decrypt_dict(token: str) -> Dict[str, Any]:
    return json.loads(decrypt_str(token))


SENSITIVE_KEYS = {"card_number", "cvv", "otp", "token", "account_number", "upi_vpa"}


def scrub_payload(
    payload: Dict[str, Any],
    sensitive_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return a copy of ``payload`` safe for logs/DB: sensitive fields are
    replaced by their encrypted form."""
    keys = set(sensitive_keys or []) | SENSITIVE_KEYS
    cleaned: Dict[str, Any] = {}
    for field, value in payload.items():
        if field.lower() in keys and value:
            cleaned[field] = encrypt_str(str(value))
        elif field == "email":
            cleaned[field] = mask_email(value)
        elif field == "phone":
            cleaned[field] = mask_phone(value)
        else:
            cleaned[field] = value
    return cleaned


def pseudonymize(value: str) -> str:
    """Deterministic hash for analytics joins without exposing the raw value."""
    salt = get_settings().secret_key.encode("utf-8")
    digest = hashlib.sha256(salt + value.lower().encode("utf-8")).hexdigest()
    return digest[:16]
