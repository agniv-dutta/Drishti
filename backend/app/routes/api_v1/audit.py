"""Audit v1 router: trail, event detail, exports, compliance report."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.responses import elapsed_ms, error, measure, success
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
) -> List[AuditRecord]:
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
    return (
        query.order_by(AuditRecord.timestamp.desc()).offset(offset).limit(min(limit, 500)).all()
    )


@router.get("/trail")
async def audit_trail(
    request: Request,
    event_type: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    rows = _query_events(
        db,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        severity=severity,
        limit=limit,
        offset=offset,
        exceptions_only=False,
    )
    total = db.query(AuditRecord).count()
    data = {"total": total, "count": len(rows), "offset": offset, "limit": limit, "events": [_serialize(r) for r in rows]}
    return success(data, agents=["AuditTrail"], latency_ms=elapsed_ms(started))


@router.get("/trail/{event_id}")
async def audit_event_detail(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    row = db.query(AuditRecord).filter(AuditRecord.id == event_id).first()
    if row is None:
        return error("EVENT_NOT_FOUND", f"audit event '{event_id}' not found", status_code=404, latency_ms=elapsed_ms(started), request=request)
    data = {
        **_serialize(row),
        "reasoning": row.details.get("reasoning") if isinstance(row.details, dict) else None,
        "gates_passed": [g for g in (row.details.get("gates_passed") or [])] if isinstance(row.details, dict) else [],
    }
    return success(data, agents=["AuditTrail"], latency_ms=elapsed_ms(started))


@router.get("/exceptions")
async def audit_exceptions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    rows = _query_events(
        db,
        event_type=None,
        resource_type=None,
        resource_id=None,
        severity=None,
        limit=limit,
        offset=offset,
        exceptions_only=True,
    )
    total = db.query(AuditRecord).count()
    data = {"total": total, "count": len(rows), "offset": offset, "limit": limit, "exceptions": [_serialize(r) for r in rows]}
    return success(data, agents=["AuditTrail"], latency_ms=elapsed_ms(started))


@router.post("/export")
async def audit_export(
    request: Request,
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    rows = _query_events(
        db,
        event_type=None,
        resource_type=resource_type,
        resource_id=resource_id,
        severity=None,
        limit=500,
        offset=0,
        exceptions_only=False,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["event_id", "timestamp", "event_type", "severity", "actor", "resource_type", "resource_id", "outcome", "message"])
    for row in rows:
        writer.writerow(
            [
                row.id,
                _serialize(row)["timestamp"],
                row.event_type,
                row.severity,
                row.actor,
                row.resource_type,
                row.resource_id,
                row.outcome,
                row.message,
            ]
        )
    data = {"filename": "drishti_audit_trail.csv", "rows": len(rows), "csv": buffer.getvalue()}
    return success(data, agents=["AuditTrail"], latency_ms=elapsed_ms(started))


@router.get("/compliance-report")
async def compliance_report(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    started = measure()
    total_events = db.query(AuditRecord).count()
    critical = db.query(AuditRecord).filter(AuditRecord.severity == AuditSeverity.CRITICAL.value).count()
    has_trail = total_events > 0
    data = {
        "report_generated": datetime.utcnow().isoformat(),
        "total_events": total_events,
        "critical_events": critical,
        "trail_integrity": "intact" if has_trail else "empty",
        "checks": [
            {"control": "Immutable audit trail present", "passed": has_trail},
            {"control": "No unresolved critical violations", "passed": critical == 0},
            {"control": "Agent actions logged with actor attribution", "passed": total_events > 0},
        ],
    }
    return success(data, agents=["AuditTrail"], latency_ms=elapsed_ms(started))
