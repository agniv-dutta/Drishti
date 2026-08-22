"""Generate synthetic payment batches.

Modes:
    --out data/batch.json     write payloads to a JSON file
    --api-url http://...      POST them to a running Drishti instance
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic failed-payment batches")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--success-ratio", type=float, default=0.35)
    parser.add_argument("--out", type=Path, help="Write batch JSON here instead of POSTing")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="dev-key-1")
    args = parser.parse_args()

    from app.utils.mock_data import generate_payment_batch

    batch = generate_payment_batch(
        args.count,
        seed=args.seed,
        success_ratio=args.success_ratio,
    )
    failed = sum(1 for p in batch if p["status"] == "failed")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(batch, indent=2), encoding="utf-8")
        print(f"Wrote {len(batch)} payments ({failed} failed) -> {args.out}")
        return

    import httpx

    url = f"{args.api_url.rstrip('/')}/api/v1/payment/ingest"
    sent = 0
    with httpx.Client(timeout=10.0) as client:
        for payload in batch:
            if payload["status"] != "failed":
                continue  # recovery API ingests failure events
            response = client.post(url, json=payload, headers={"X-API-Key": args.api_key})
            response.raise_for_status()
            sent += 1
            time.sleep(0.02)  # be gentle
    print(f"Posted {sent} failed payments to {url}")


if __name__ == "__main__":
    main()
