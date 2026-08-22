"""Train the payment-recovery risk AutoML model and export inference artifacts.

Usage:
    python scripts/train_recovery_risk_automl.py [--rows 50000] [--seed 42]
        [--time-budget 180] [--backends auto] [--out-dir models/recovery_risk_automl]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ml.automl_pipeline import print_report, run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Recovery-risk AutoML trainer")
    parser.add_argument("--rows", type=int, default=50_000, help="Synthetic dataset size")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--time-budget", type=int, default=180, help="Per-AutoML-backend search budget (seconds)")
    parser.add_argument(
        "--backends",
        default="auto",
        help="auto or comma list from: h2o,autogluon,flaml,sklearn",
    )
    parser.add_argument("--out-dir", default=None, help="Artifact directory override")
    args = parser.parse_args()

    report = run_pipeline(
        n_rows=args.rows,
        seed=args.seed,
        flaml_time_budget=args.time_budget,
        backends=args.backends,
        out_dir=Path(args.out_dir) if args.out_dir else None,
    )
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
