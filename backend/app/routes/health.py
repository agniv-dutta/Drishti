"""Health & readiness probes."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter
from sqlalchemy import text

from app.cache.redis_client import get_cache
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.database.session import get_database_mode, get_engine

router = APIRouter(tags=["health"])
logger = get_logger("drishti.health")


def _check_db() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("health.db_check_failed", error=str(exc))
        return False


async def _check_cache() -> bool:
    try:
        return await (await get_cache()).ping()
    except Exception:  # noqa: BLE001
        return False


@router.get("/", include_in_schema=False)
async def root() -> Dict:
    settings = get_settings()
    return {
        "service": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "docs": "/docs",
    }


@router.get("/health")
async def health() -> Dict:
    db_ok = _check_db()
    cache_ok = await _check_cache()
    status = "ok" if db_ok else "degraded"
    database_mode = get_database_mode()
    return {
        "status": status,
        "components": {
            "database": "up" if db_ok else "down",
            "database_mode": database_mode,
            "cache": "up" if cache_ok else "fallback-memory",
        },
        "llm_reasoning": "enabled" if get_settings().llm_enabled else "rule-engine",
    }
