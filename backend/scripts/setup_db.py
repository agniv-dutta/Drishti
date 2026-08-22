"""Initialize the Drishti database schema (and optionally seed test data).

Usage:
    python scripts/setup_db.py                 # create tables only
    python scripts/setup_db.py --seed 100      # also ingest 100 synthetic payments
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup the Drishti database")
    parser.add_argument("--seed", type=int, default=0, help="Number of synthetic payments to ingest")
    parser.add_argument("--drop", action="store_true", help="Drop tables before creating")
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.core.logging_config import configure_logging, get_logger
    from app.database.models import Base
    from app.database.session import get_engine, init_db

    configure_logging()
    logger = get_logger("drishti.scripts")

    init_db()
    if args.drop:
        logger.warning("setup_db.dropping_tables")
        Base.metadata.drop_all(bind=get_engine())
        init_db()

    if args.seed > 0:
        asyncio.run(_seed(args.seed))

    logger.info("setup_db.complete", url=get_settings().database_url)


async def _seed(count: int) -> None:
    from app.agents import get_supervisor
    from app.database.session import dispose_db, get_session_factory
    from app.schemas.payment_schemas import PaymentIngestRequest
    from app.utils.mock_data import generate_payment_batch

    db = get_session_factory()()
    supervisor = get_supervisor()
    ingested = duplicates = 0
    try:
        for payload in generate_payment_batch(count, seed=42):
            _, duplicate = await supervisor.ingest_payment(db, PaymentIngestRequest(**payload))
            duplicates += int(duplicate)
            ingested += 1 - int(duplicate)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        dispose_db()
    print(f"Seeded {ingested} payments ({duplicates} duplicates ignored).")


if __name__ == "__main__":
    main()
