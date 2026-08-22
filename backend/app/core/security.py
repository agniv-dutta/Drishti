"""Authentication & authorization utilities.

- API-key guard (machine-to-machine traffic) via ``X-API-Key`` header.
- JWT issuing/verification (python-jose) for user-facing tokens.
- PBKDF2 password hashing helpers (no external passlib dependency).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

_api_key_scheme = APIKeyHeader(name=settings.api_key_header, auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)

PBKDF2_ITERATIONS = 120_000
PBKDF2_ALGORITHM = "sha256"


# ---------------------------------------------------------------------------
# Password / secret hashing (PBKDF2-HMAC-SHA256)
# ---------------------------------------------------------------------------

def hash_secret(secret: str, salt: Optional[str] = None) -> str:
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        secret.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"{salt_hex}${digest}"


def verify_secret(secret: str, hashed: str) -> bool:
    try:
        salt_hex, expected = hashed.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        secret.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    ).hex()
    return hmac.compare_digest(candidate, expected)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(
    subject: str,
    expires_minutes: Optional[int] = None,
    claims: Optional[Dict[str, Any]] = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload: Dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": settings.app_name.lower(),
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:  # expired, malformed, bad signature
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def require_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> Dict[str, Any]:
    """Dependency enforcing ``Authorization: Bearer <jwt>``."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials)


# ---------------------------------------------------------------------------
# API key auth (primary mechanism for service endpoints)
# ---------------------------------------------------------------------------

async def require_api_key(api_key: Optional[str] = Security(_api_key_scheme)) -> str:
    """Validate the configured API keys; returns the caller's key on success."""
    valid_keys = get_settings().valid_api_keys
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    matched = any(hmac.compare_digest(api_key, candidate) for candidate in valid_keys)
    if not matched:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return api_key


def generate_api_key(prefix: str = "dsh") -> str:
    """Utility for provisioning new client keys."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"
