"""Database engine, session factory and FastAPI dependencies."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_session_factory: sessionmaker | None = None


def _create_engine():
    settings = get_settings()
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
    return create_engine(url, **kwargs)


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

    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        Path(settings.database_url.replace("sqlite:///", "", 1)).parent.mkdir(
            parents=True, exist_ok=True
        )
    Base = app.database.models.Base
    Base.metadata.create_all(bind=get_engine())
    get_logger("drishti.db").info("database.ready", url=_safe_url())


def dispose_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def _safe_url() -> str:
    url = get_settings().database_url
    if "@" in url:  # mask credentials in logs
        scheme_and_rest = url.split("@", 1)
        prefix = scheme_and_rest[0].rsplit(":", 1)[0]
        return f"{prefix}:***@{scheme_and_rest[1]}"
    return url
