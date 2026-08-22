"""Generate a deterministic 50k-row recovery dataset for AutoML training.

The target is assigned from a latent recovery score, then stratified to exact
full/partial/failed ratios. This preserves feature relationships while making
class proportions stable across runs.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

DECLINE_REASONS = (
    ("insufficient_funds", 30),
    ("declined_by_issuer", 25),
    ("timeout", 20),
    ("invalid_details", 10),
    ("fraud_suspected", 8),
    ("customer_cancelled", 4),
    ("technical_error", 3),
)
DEVICE_TYPES = (("mobile", 60), ("web", 30), ("api", 10))
LOCATIONS = (
    ("Mumbai", 22), ("Bangalore", 20), ("Delhi", 18), ("Hyderabad", 12),
    ("Chennai", 10), ("Pune", 8), ("Kolkata", 5), ("Ahmedabad", 5),
)
CUSTOMER_TYPES = (("consumer", 80), ("business", 20))

FIELDNAMES = [
    "merchant_id", "payment_id", "decline_reason", "amount_inr",
    "customer_tenure_years", "device_type", "hour_utc", "is_peak_hour",
    "location", "customer_type", "failure_count", "retry_attempts",
    "contact_on_weekend", "contact_in_evening", "recovery_success",
]


def _weighted_choice(rng: random.Random, values: tuple[tuple[str, int], ...]) -> str:
    return rng.choices([value for value, _ in values], weights=[weight for _, weight in values], k=1)[0]


def _amount(rng: random.Random) -> float:
    # Median is intentionally well below the upper bound, with a long tail.
    value = rng.lognormvariate(7.15, 1.15)
    return round(min(max(value, 100.0), 50_000.0), 2)


def generate_dataset(
    merchant_count: int = 50,
    payments_per_merchant: int = 1_000,
    seed: int = 20260822,
) -> list[dict[str, object]]:
    """Generate reproducible failed-payment records and stratified outcomes."""
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for merchant_number in range(1, merchant_count + 1):
        merchant_id = f"merchant_{merchant_number:03d}"
        for payment_number in range(1, payments_per_merchant + 1):
            hour = rng.choices(range(24), weights=[2, 2, 2, 2, 2, 3, 4, 5, 7, 8, 8, 7, 6, 6, 6, 7, 9, 12, 14, 13, 10, 7, 4, 3], k=1)[0]
            amount = _amount(rng)
            tenure = min(rng.expovariate(0.8), 5.0)
            failure_count = rng.choices(range(1, 7), weights=[34, 25, 17, 11, 7, 6], k=1)[0]
            retry_attempts = rng.choices(range(0, 4), weights=[35, 35, 20, 10], k=1)[0]
            weekend = rng.random() < 2 / 7
            evening = hour in {17, 18, 19, 20, 21, 22}
            customer_type = _weighted_choice(rng, CUSTOMER_TYPES)
            # Higher score means a more recoverable payment.
            score = (
                1.0
                - 0.22 * (amount / 50_000)
                + 0.08 * retry_attempts
                + 0.10 * (weekend and evening)
                + 0.04 * weekend
                + 0.03 * evening
                + 0.02 * min(tenure, 2.0) / 2
                - 0.08 * (failure_count - 1) / 5
                - 0.10 * (customer_type == "business")
                + rng.gauss(0, 0.08)
            )
            rows.append({
                "merchant_id": merchant_id,
                "payment_id": f"pay_{merchant_number:03d}_{payment_number:04d}",
                "decline_reason": _weighted_choice(rng, DECLINE_REASONS),
                "amount_inr": amount,
                "customer_tenure_years": round(tenure, 3),
                "device_type": _weighted_choice(rng, DEVICE_TYPES),
                "hour_utc": hour,
                "is_peak_hour": int(hour in {8, 9, 10, 17, 18, 19, 20}),
                "location": _weighted_choice(rng, LOCATIONS),
                "customer_type": customer_type,
                "failure_count": failure_count,
                "retry_attempts": retry_attempts,
                "contact_on_weekend": int(weekend),
                "contact_in_evening": int(evening),
                "_score": score,
            })

    rows.sort(key=lambda row: float(row["_score"]), reverse=True)
    full_count = len(rows) * 40 // 100
    partial_count = len(rows) * 20 // 100
    for index, row in enumerate(rows):
        row["recovery_success"] = (
            "full" if index < full_count
            else "partial" if index < full_count + partial_count
            else "failed"
        )
        row.pop("_score")
    rows.sort(key=lambda row: str(row["payment_id"]))
    return rows


def write_csv(output: Path, rows: list[dict[str, object]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate recovery-training CSV data")
    parser.add_argument("--merchants", type=int, default=50)
    parser.add_argument("--payments-per-merchant", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--out", type=Path, default=Path("data/recovery_training.csv"))
    args = parser.parse_args()
    rows = generate_dataset(args.merchants, args.payments_per_merchant, args.seed)
    write_csv(args.out, rows)
    print(f"Wrote {len(rows):,} rows to {args.out}")


if __name__ == "__main__":
    main()
