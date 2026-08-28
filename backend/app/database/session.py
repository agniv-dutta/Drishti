"""Database engine, session factory and FastAPI dependencies."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_session_factory: sessionmaker | None = None
_resolved_database_url: str | None = None
_database_mode: str | None = None


def _create_engine():
    settings = get_settings()
    url = _resolve_database_url()
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
    return create_engine(url, **kwargs)


def _resolve_database_url() -> str:
    """Prefer the configured database, but fall back to local SQLite in dev.

    This keeps `uvicorn main:app` usable on fresh machines even when a local
    Postgres instance is not running yet.
    """
    global _resolved_database_url, _database_mode
    if _resolved_database_url is not None:
        return _resolved_database_url

    settings = get_settings()
    url = settings.database_url
    if url.startswith("sqlite"):
        _resolved_database_url = url
        _database_mode = "sqlite"
        return url

    if settings.is_production:
        _resolved_database_url = url
        _database_mode = "postgresql"
        return url

    try:
        engine = create_engine(url, pool_pre_ping=True, future=True)
        with engine.connect():
            pass
        _resolved_database_url = url
        _database_mode = "postgresql"
        return url
    except OperationalError:
        fallback = "sqlite:///./drishti.db"
        logger.warning(
            "database.fallback_to_sqlite requested_url=%s fallback_url=%s",
            _safe_url(url),
            fallback,
        )
        _resolved_database_url = fallback
        _database_mode = "sqlite-fallback"
        return fallback


def get_database_mode() -> str:
    """Return the active database mode for observability and health checks."""
    if _database_mode is None:
        _resolve_database_url()
    return _database_mode or "unknown"


def get_engine():
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables (dev/bootstrap convenience; Alembic owns real migrations)."""
    from app.core.logging_config import get_logger
    import app.database.models  # noqa: F401 - register mappings

    database_url = _resolve_database_url()
    if database_url.startswith("sqlite"):
        Path(database_url.replace("sqlite:///", "", 1)).parent.mkdir(
            parents=True, exist_ok=True
        )
    Base = app.database.models.Base
    Base.metadata.create_all(bind=get_engine())
    get_logger("drishti.db").info("database.ready", url=_safe_url())


def dispose_db() -> None:
    global _engine, _session_factory, _resolved_database_url, _database_mode
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _resolved_database_url = None
    _database_mode = None


def _safe_url(url: str | None = None) -> str:
    url = url or _resolve_database_url() or get_settings().database_url
    if "@" in url:  # mask credentials in logs
        scheme_and_rest = url.split("@", 1)
        prefix = scheme_and_rest[0].rsplit(":", 1)[0]
        return f"{prefix}:***@{scheme_and_rest[1]}"
    return url
