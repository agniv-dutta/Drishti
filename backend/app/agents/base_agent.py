"""Abstract agent base class shared by all Drishti agents.

Provides structured logging, audit-trail emission (JSONL), and an optional
Groq reasoning hook that degrades gracefully to ``None`` when no API key is
configured - the rule engine remains fully functional offline.
"""

from __future__ import annotations

import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.logging_config import get_audit_trail, get_logger
from app.models.audit import AuditEventType, AuditLogEntry, AuditSeverity


class BaseAgent(ABC):
    name: str = "base"
    description: str = ""

    def __init__(self) -> None:
        self.log = get_logger(f"drishti.agent.{self.name}")
        # Optional DB session; when bound, every audit event is also persisted
        # to the ``audits`` table (JSONL remains the forensic source of truth).
        self.db = None

    def bind_db(self, db) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def audit(
        self,
        event_type: AuditEventType,
        *,
        resource_type: str,
        resource_id: str,
        outcome: str,
        severity: AuditSeverity = AuditSeverity.INFO,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            severity=severity,
            actor=self.name,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            message=message,
            details=details or {},
            is_exception=event_type in AuditEventType.exception_types()
            or severity == AuditSeverity.CRITICAL,
        )
        get_audit_trail().record(
            event_type=entry.event_type.value,
            actor=entry.actor,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            outcome=entry.outcome,
            severity=entry.severity.value,
            details={"message": entry.message, **entry.details},
        )
        if self.db is not None:
            try:
                from app.database.models import AuditRecord

                self.db.add(AuditRecord.from_entry(entry))
                self.db.flush()
            except Exception as exc:  # noqa: BLE001 - audit persistence is best-effort
                self.log.warning("audit.db_persist_failed", error=str(exc))
        return entry

    # ------------------------------------------------------------------
    # Optional LLM reasoning (Groq/OpenAI-compatible endpoint)
    # ------------------------------------------------------------------
    @property
    def llm_enabled(self) -> bool:
        return get_settings().llm_enabled

    def llm_complete(self, system: str, prompt: str) -> Optional[str]:
        """Call Groq; returns None on any failure so callers can fall back."""
        settings = get_settings()
        if not settings.llm_enabled:
            return None
        started = time.perf_counter()
        try:
            from openai import OpenAI  # lazy import keeps startup fast without the dep

            client = OpenAI(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
            response = client.chat.completions.create(
                model=settings.groq_model,
                max_tokens=settings.llm_max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=settings.llm_temperature,
            )
            text = response.choices[0].message.content if response.choices else ""
            self.log.info(
                "llm.complete",
                model=settings.groq_model,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                input_tokens=getattr(response.usage, "input_tokens", None),
                output_tokens=getattr(response.usage, "output_tokens", None),
            )
            return text or None
        except Exception as exc:  # noqa: BLE001 - never break the pipeline on LLM errors
            self.log.warning("llm.failed_falling_back_to_rules", error=str(exc))
            return None

    @staticmethod
    def extract_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
        """Best-effort JSON object extraction from an LLM response."""
        if not text:
            return None
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            import json

            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any): ...
