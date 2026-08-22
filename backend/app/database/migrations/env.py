"""Alembic migration environment for Drishti.

Invoked via:
    alembic -c app/database/migrations/alembic.ini upgrade head
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `backend/` importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import get_settings  # noqa: E402
import app.database.models  # noqa: F402,E401  # registers all mappings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = app.database.models.Base.metadata


def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite"):
        # Alembic runs offline-safe with sqlite too; pass through as-is.
        return url
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for sqlite ALTER support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config_section = config.get_section(config.config_ini_section) or {}
    config_section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
