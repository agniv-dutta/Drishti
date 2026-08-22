"""Structured logging with structlog + append-only JSONL audit trail.

- ``configure_logging``: idempotent global setup (console or JSON rendering).
- ``get_logger(name)``: returns a bound structlog logger.
- ``AuditTrail``: tamper-evident-ish JSONL writer used alongside the DB audit
  table so every agent decision is reconstructable after the fact.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

import structlog

from app.core.config import get_settings

_configured = False
_audit_lock = Lock()
_audit_trail: Optional["AuditTrail"] = None


def configure_logging() -> None:
    """Configure structlog + stdlib logging once per process."""
    global _configured
    if _configured:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer() if settings.log_json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # uvicorn access logs duplicate our structured http.request events
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str = "drishti"):
    configure_logging()
    return structlog.get_logger(name)


class AuditTrail:
    """Thread-safe append-only JSONL audit log.

    Every line is a self-contained event dict. Complements the ``audits``
    database table written by the supervisor agent.
    """

    def __init__(self, path: Optional[str] = None):
        self._path = Path(path or get_settings().audit_log_file)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        event_type: str,
        actor: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        severity: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "actor": actor,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "outcome": outcome,
            "severity": severity.upper(),
            "details": details or {},
        }
        line = json.dumps(entry, default=str, ensure_ascii=False)
        with _audit_lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

        logger = get_logger("drishti.audit")
        log = logger.error if entry["severity"] == "CRITICAL" else (
            logger.warning if entry["severity"] == "WARNING" else logger.info
        )
        log("audit.event", **entry)
        return entry


def get_audit_trail() -> AuditTrail:
    """Process-wide AuditTrail singleton."""
    global _audit_trail
    with _audit_lock:
        if _audit_trail is None:
            _audit_trail = AuditTrail()
        return _audit_trail
