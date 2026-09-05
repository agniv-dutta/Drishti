"""Unified REST API response envelope for Drishti v1.

All versioned endpoints return a consistent envelope:

    {
      "status": "success" | "error",
      "data": {...} | null,
      "metadata": {
        "timestamp": "...",
        "latency_ms": ...,
        "agent_involved": ["PaymentAnalyzer", ...],
        "confidence": 0.0-1.0
      },
      "error": { "code", "message", "details" } | null
    }
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raise with a stable error code + message to produce a structured error response."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def success(
    data: Any = None,
    *,
    agents: Optional[List[str]] = None,
    confidence: Optional[float] = None,
    message: str = "OK",
    latency_ms: Optional[float] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a success envelope."""
    metadata: Dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "agent_involved": agents or [],
        "confidence": confidence,
    }
    if extra_meta:
        metadata.update(extra_meta)
    return {
        "status": "success",
        "message": message,
        "data": data,
        "metadata": metadata,
        "error": None,
    }


def error(
    code: str,
    message: str,
    *,
    details: Optional[Any] = None,
    status_code: int = 400,
    latency_ms: Optional[float] = None,
    request: Optional[Request] = None,
) -> JSONResponse:
    metadata: Dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "agent_involved": [],
        "confidence": None,
        "path": request.url.path if request else None,
    }
    body = {
        "status": "error",
        "message": "Error",
        "data": None,
        "metadata": metadata,
        "error": {"code": code, "message": message, "details": details},
    }
    return JSONResponse(status_code=status_code, content=body)


def measure() -> float:
    """Return a monotonic start timestamp; pass difference to success()/error()."""
    return time.perf_counter()


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
