"""Seed the database with realistic test data for the dashboard.

Usage: cd backend && python -m scripts.seed_dashboard
"""

from __future__ import annotations

import random
import string
import sys
from datetime import timedelta

sys.path.insert(0, ".")

from app.database.models import PaymentRecord, RecoveryRecord
from app.database.session import get_engine, get_session_factory, init_db
from app.models.payment import utcnow
from app.models.recovery import RecoveryStatus
from app.utils.encryption import encrypt_dict

STRATEGIES = ["smart_retry", "sms", "email", "call", "offer"]
STATUS_POOL = [
    (RecoveryStatus.SUCCEEDED.value, 0.45),
    (RecoveryStatus.FAILED.value, 0.25),
    (RecoveryStatus.PENDING.value, 0.15),
    (RecoveryStatus.PLANNED.value, 0.15),
]

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Kabir", "Anaya", "Diya", "Rohan", "Rahul", "Priya"]
LAST = ["Sharma", "Verma", "Gupta", "Mehta", "Patel", "Reddy", "Iyer", "Nair", "Joshi", "Kapoor"]
BANKS = ["HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Mahindra"]
REASONS = ["insufficient_funds", "otp_timeout", "gateway_declined", "card_expired", "risk_blocked"]


def _id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=24))


CHANNELS = [
    ("sms", 25, 1.20),
    ("voice_ivr", 40, 2.50),
    ("email", 15, 0.80),
    ("offer", 20, 4.00),
]


def _channel_outcome(rng: random.Random, status: str) -> dict | None:
    """Build a result_json with realistic channel costs per attempt."""
    if status == RecoveryStatus.PLANNED.value:
        return None
    channel, weight_inr, cost_inr = rng.choices(CHANNELS, weights=[w for _, w, _ in CHANNELS], k=1)[0]
    attempt_status = "succeeded" if status == RecoveryStatus.SUCCEEDED.value else "failed"
    return {
        "outcomes": [
            {
                "channel": channel,
                "status": attempt_status,
                "cost_incurred_paise": int(cost_inr * 100),
                "recovered_amount_paise": 0,
            }
        ]
    }


def seed(n: int = 30) -> None:
    init_db()
    engine = get_engine()
    factory = get_session_factory()
    db = factory()

    # Clear previously seeded rows to avoid duplicates on re-run.
    with engine.begin() as conn:
        conn.execute(
            RecoveryRecord.__table__.delete().where(
                RecoveryRecord.payment_id.in_(
                    db.query(PaymentRecord.id).filter(PaymentRecord.gateway_payment_id.like("pay_seed_%"))
                )
            )
        )
        conn.execute(PaymentRecord.__table__.delete().where(PaymentRecord.gateway_payment_id.like("pay_seed_%")))

    now = utcnow()
    rng = random.Random(42)

    for i in range(n):
        # Ensure even spread: some in last 7d, some in 7-30d, some in 30-90d
        if i < 8:
            age_days = rng.uniform(0.2, 6.5)
        elif i < 18:
            age_days = rng.uniform(7, 29)
        else:
            age_days = rng.uniform(30, 90)
        created = now - timedelta(days=age_days)

        first = rng.choice(FIRST)
        last = rng.choice(LAST)
        pid = _id()
        amount = round(rng.uniform(200, 85000), 2)
        paise = int(amount * 100)
        phone = f"+91{random.choice(['6','7','8','9'])}{random.randint(100000000, 999999999)}"
        email = f"{first.lower()}.{last.lower()}{random.randint(1,999)}@example.com"
        contact_encrypted = encrypt_dict({"email": email, "phone": phone})

        status_choice = rng.choices(
            [s for s, _ in STATUS_POOL],
            weights=[w for _, w in STATUS_POOL],
            k=1,
        )[0]

        strategy = rng.choice(STRATEGIES)
        recovered = paise if status_choice == RecoveryStatus.SUCCEEDED.value else 0
        attempts = rng.randint(1, 4) if status_choice != RecoveryStatus.PLANNED.value else 0

        payment = PaymentRecord(
            id=pid,
            order_id=f"order_seed_{pid[:8]}",
            gateway_payment_id=f"pay_seed_{pid[:8]}",
            customer_name=f"{first} {last}",
            customer_email_masked=f"{first.lower()}***@***.com",
            customer_contact_encrypted=contact_encrypted,
            amount_paise=paise,
            currency="INR",
            method=rng.choice(["upi", "card", "netbanking", "wallet"]),
            status="failed",
            error_code=rng.choice(REASONS),
            error_description=f"{rng.choice(REASONS).replace('_',' ').title()} at {rng.choice(BANKS)}",
            attempt_number=rng.randint(1, 3),
            meta={"source": "seed"},
            created_at=created,
        )
        db.add(payment)

        recovery = RecoveryRecord(
            id=_id(),
            payment_id=pid,
            strategy=strategy,
            status=status_choice,
            priority=rng.choice(["P1", "P2", "P3"]),
            risk_score=round(rng.uniform(0.1, 0.95), 2),
            expected_amount_paise=paise,
            recovered_amount_paise=recovered,
            cost_paise=rng.randint(0, 50) if status_choice == RecoveryStatus.SUCCEEDED.value else 0,
            attempts=attempts,
            max_attempts=4,
            executed_at=created + timedelta(hours=rng.uniform(0.5, 6)) if attempts > 0 else None,
            completed_at=created + timedelta(hours=rng.uniform(1, 12)) if status_choice in (RecoveryStatus.SUCCEEDED.value, RecoveryStatus.FAILED.value) else None,
            created_at=created,
            updated_at=created + timedelta(hours=rng.uniform(1, 8)),
            result_json=_channel_outcome(rng, status_choice),
        )
        db.add(recovery)

    db.commit()

    from sqlalchemy import func
    q = db.query(
        func.count(PaymentRecord.id),
        func.sum(RecoveryRecord.recovered_amount_paise),
        func.count(RecoveryRecord.id).filter(RecoveryRecord.status == RecoveryStatus.SUCCEEDED.value),
    ).join(RecoveryRecord, RecoveryRecord.payment_id == PaymentRecord.id)
    total, recovered_paise, success_count = q.one()
    rate = round(success_count / total * 100, 1) if total else 0
    print(f"Seeded {n} payments + {n} recovery records spanning 95 days.")
    print(f"  Total: {total} payments | Recovered: INR {recovered_paise/100:,.0f} | Rate: {rate}%")

    # Show period breakdown
    for days in [7, 30, 90]:
        cutoff = now - timedelta(days=days)
        cnt = db.query(func.count(RecoveryRecord.id)).filter(RecoveryRecord.created_at >= cutoff).scalar()
        print(f"  Last {days:>2} days: {cnt} recovery records")

    db.close()


if __name__ == "__main__":
    seed()
