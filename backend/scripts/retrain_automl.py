"""Run the weekly recovery-model retraining and promotion checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.database.session import get_session_factory, init_db
from app.ml.retraining import RetrainingPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrain and stage the recovery model")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--promote-only", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    model_dir = args.model_dir or settings.model_dir
    baseline = args.baseline or str(Path(model_dir).parent / "data" / "recovery_training.csv")

    init_db()
    session = get_session_factory()()
    try:
        pipeline = RetrainingPipeline(model_dir=model_dir, baseline_path=baseline)
        promoted = pipeline.promote_staging()
        result = None if args.promote_only else pipeline.run(session, seed=args.seed)
        print({"promotion": promoted.__dict__ if promoted else None, "retraining": result.__dict__})
    finally:
        session.close()


if __name__ == "__main__":
    main()
