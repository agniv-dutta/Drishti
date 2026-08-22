"""Audit endpoints: query the structured trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.database.models import AuditRecord
from app.database.session import get_db
from app.models.audit import AuditSeverity

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_api_key)])


def _serialize(row: AuditRecord) -> Dict[str, Any]:
    return {
        "event_id": row.id,
        "timestamp": row.timestamp.isoformat() if isinstance(row.timestamp, datetime) else str(row.timestamp),
        "event_type": row.event_type,
        "severity": row.severity,
        "actor": row.actor,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "outcome": row.outcome,
        "message": row.message,
        "details": row.details or {},
        "is_exception": row.is_exception,
    }


def _query_events(
    db: Session,
    *,
    event_type: Optional[str],
    resource_type: Optional[str],
    resource_id: Optional[str],
    severity: Optional[str],
    limit: int,
    offset: int,
    exceptions_only: bool,
) -> tuple[List[Dict[str, Any]], int]:
    query = db.query(AuditRecord)
    if exceptions_only:
        query = query.filter(
            (AuditRecord.is_exception.is_(True))
            | (AuditRecord.severity == AuditSeverity.CRITICAL.value)
            | (AuditRecord.severity == AuditSeverity.WARNING.value)
        )
    if event_type:
        query = query.filter(AuditRecord.event_type == event_type)
    if resource_type:
        query = query.filter(AuditRecord.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditRecord.resource_id == resource_id)
    if severity:
        query = query.filter(AuditRecord.severity == severity.upper())

    total = query.count()
    rows = (
        query.order_by(AuditRecord.timestamp.desc())
        .offset(offset)
        .limit(min(limit, 500))
        .all()
    )
    return [_serialize(row) for row in rows], total


@router.get("/trail")
async def audit_trail(
    event_type: Optional[str] = Query(default=None, description="e.g. payment_analyzed"),
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None, description="INFO | WARNING | CRITICAL"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    events, total = _query_events(
        db,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        severity=severity,
        limit=limit,
        offset=offset,
        exceptions_only=False,
    )
    return {"success": True, "total": total, "count": len(events), "events": events}


@router.get("/exceptions")
async def audit_exceptions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """WARNING/CRITICAL events and flagged exceptions - the ops triage queue."""
    events, total = _query_events(
        db,
        event_type=None,
        resource_type=None,
        resource_id=None,
        severity=None,
        limit=limit,
        offset=offset,
        exceptions_only=True,
    )
    return {"success": True, "total": total, "count": len(events), "exceptions": events}
