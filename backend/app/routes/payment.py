"""Payment endpoints: ingest, analyze, detail."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents import PaymentNotFoundError, SupervisorError, get_supervisor
from app.core.security import require_api_key
from app.database.models import PaymentRecord, RecoveryRecord
from app.database.session import get_db
from app.schemas.payment_schemas import (
    AnalysisOut,
    AnalyzeRequest,
    AnalyzeResponse,
    PaymentDetailResponse,
    PaymentIngestRequest,
    PaymentIngestResponse,
    PaymentRecoveryRef,
)

router = APIRouter(prefix="/payment", tags=["payment"], dependencies=[Depends(require_api_key)])


@router.post("/ingest", response_model=PaymentIngestResponse)
async def ingest_payment(
    payload: PaymentIngestRequest,
    db: Session = Depends(get_db),
) -> PaymentIngestResponse:
    """Ingest a (typically failed) payment event for the recovery pipeline."""
    record, duplicate = await get_supervisor().ingest_payment(db, payload)
    return PaymentIngestResponse(
        payment_id=record.id,
        order_id=record.order_id,
        status=record.status,
        received_at=record.created_at,
        duplicate=duplicate,
        message="duplicate ignored" if duplicate else "Payment ingested successfully",
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_payment(
    payload: AnalyzeRequest,
    db: Session = Depends(get_db),
) -> AnalyzeResponse:
    """Run failure analysis + risk scoring for one payment."""
    started = time.perf_counter()
    try:
        record, analysis = await get_supervisor().analyze_payment(
            db, payload.payment_id, force=payload.force_reanalyze
        )
    except PaymentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AnalyzeResponse(
        payment_id=record.id,
        analysis=AnalysisOut(**analysis.model_dump(mode="json")),
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )


@router.get("/{payment_id}", response_model=PaymentDetailResponse)
async def get_payment(
    payment_id: str,
    db: Session = Depends(get_db),
) -> PaymentDetailResponse:
    """PII-safe payment detail with linked recovery summary."""
    record = db.get(PaymentRecord, payment_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"payment '{payment_id}' not found")

    recoveries = (
        db.query(RecoveryRecord)
        .filter(RecoveryRecord.payment_id == payment_id)
        .order_by(RecoveryRecord.created_at.desc())
        .all()
    )
    return PaymentDetailResponse(
        transaction=record.public_view(),
        recoveries=[
            PaymentRecoveryRef(plan_id=r.id, strategy=r.strategy, status=r.status)
            for r in recoveries
        ],
    )
