"""Shared pytest configuration and fixtures for the Drishti suite.

Environment overrides are applied at import time (before any ``app.*`` import)
so the cached Settings singleton picks up test values deterministically.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Test environment (MUST run before importing app modules)
# ---------------------------------------------------------------------------
_TEST_DIR = Path(tempfile.mkdtemp(prefix="drishti-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR / 'test_drishti.db'}"
os.environ["DRISHTI_API_KEYS"] = "test-api-key"
os.environ.pop("REDIS_URL", None)  # force in-memory cache fallback
os.environ["AUDIT_LOG_FILE"] = str(_TEST_DIR / "audit.jsonl")
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ENVIRONMENT"] = "development"
# Deterministic Fernet key: base64("0" * 32)
os.environ["ENCRYPTION_KEY"] = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
os.environ["GROQ_API_KEY"] = ""  # rule-engine mode for reproducible tests

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database.models import Base  # noqa: E402
from app.database.session import dispose_db, get_engine  # noqa: E402
from app.utils.mock_data import make_failed_payment  # noqa: E402


@pytest.fixture(scope="session")
def api_key() -> str:
    return "test-api-key"


@pytest.fixture()
def client(api_key):
    """TestClient with lifespan (creates tables) and auth header pre-set."""
    from main import app

    with TestClient(app) as test_client:
        test_client.headers.update({"X-API-Key": api_key})
        yield test_client


@pytest.fixture(autouse=True)
def _clean_database():
    """Wipe all tables after every test for full isolation."""
    yield
    from sqlalchemy import inspect

    engine = get_engine()
    existing = set(inspect(engine).get_table_names())
    if not existing:
        return
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in existing:
                conn.execute(table.delete())


@pytest.fixture()
def sample_failed_payment() -> dict:
    payload = make_failed_payment(seed=1234, age_minutes=10)
    payload["order_id"] = f"order_test_{uuid.uuid4().hex[:10]}"
    return payload


@pytest.fixture()
def ingested_payment(client, sample_failed_payment) -> dict:
    response = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
    assert response.status_code == 200, response.text
    return sample_failed_payment | {"payment_id": response.json()["payment_id"]}
