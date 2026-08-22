"""Verity LangGraph endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.agents.verity_graph import VerityGraphRunner, _normalize_websocket_auth
from app.core.security import require_api_key
from app.database.session import get_db, get_session_factory
from app.schemas.verity_schemas import VerityRunRequest, VerityRunResponse

router = APIRouter(prefix="/verity", tags=["verity"])


@router.post("/run", response_model=VerityRunResponse, dependencies=[Depends(require_api_key)])
async def run_verity_workflow(
    payload: VerityRunRequest,
    db: Session = Depends(get_db),
) -> VerityRunResponse:
    runner = VerityGraphRunner(db)
    result = await runner.run(
        payment_id=payload.payment_id,
        merchant_id=payload.merchant_id,
        user_id=payload.user_id,
        dry_run=payload.dry_run,
        thread_id=payload.thread_id,
        confidence_threshold=payload.confidence_threshold,
        contact_attempts=payload.contact_attempts,
        daily_spend_usd=payload.daily_spend_usd,
        resume=payload.resume,
    )
    return VerityRunResponse(
        thread_id=result["thread_id"],
        interrupted=bool(result["interrupted"]),
        state=result["state"],
        interrupts=result.get("interrupts"),
    )


@router.websocket("/stream")
async def stream_verity_workflow(websocket: WebSocket) -> None:
    if not _normalize_websocket_auth(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    factory = get_session_factory()
    db = factory()
    try:
        payload = await websocket.receive_json()
        request = VerityRunRequest(**payload)
        runner = VerityGraphRunner(db, emit=websocket.send_json)

        await websocket.send_json({"type": "started", "payment_id": request.payment_id})
        result = await runner.run(
            payment_id=request.payment_id,
            merchant_id=request.merchant_id,
            user_id=request.user_id,
            dry_run=request.dry_run,
            thread_id=request.thread_id,
            confidence_threshold=request.confidence_threshold,
            contact_attempts=request.contact_attempts,
            daily_spend_usd=request.daily_spend_usd,
            resume=request.resume,
        )
        await websocket.send_json({"type": "result", **result})

        while result["interrupted"]:
            message = await websocket.receive_json()
            if message.get("type") != "resume":
                await websocket.send_json(
                    {"type": "error", "message": "Expected a resume message"}
                )
                continue
            resume_payload: Any = message.get("resume")
            result = await runner.run(
                payment_id=request.payment_id,
                merchant_id=request.merchant_id,
                user_id=request.user_id,
                dry_run=request.dry_run,
                thread_id=result["thread_id"],
                confidence_threshold=request.confidence_threshold,
                contact_attempts=request.contact_attempts,
                daily_spend_usd=request.daily_spend_usd,
                resume=resume_payload,
            )
            await websocket.send_json({"type": "result", **result})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
    finally:
        db.close()

