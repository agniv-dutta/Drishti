"""Synthetic test-data generation for local development and load tests.

Deterministic when ``seed`` is provided so tests are reproducible.
"""

from __future__ import annotations

import random
import string
from datetime import timedelta
from typing import Any, Dict, List, Optional

from app.models.payment import (
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    utcnow,
)
from app.utils.validators import normalize_indian_phone

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Ishaan", "Kabir", "Anaya", "Diya",
    "Aadhya", "Myra", "Sara", "Rohan", "Rahul", "Priya", "Neha",
    "Arjun", "Kavya", "Ravi", "Sneha", "Vikram", "Ananya",
]
LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Mehta", "Patel", "Reddy", "Iyer",
    "Nair", "Joshi", "Kulkarni", "Chatterjee", "Banerjee", "Malhotra",
    "Kapoor", "Desai", "Rao",
]

BANKS = ["HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Mahindra"]

# Realistic Razorpay-style error codes weighted by frequency.
FAILURE_DISTRIBUTION: List[tuple[str, int]] = [
    (FailureReason.INSUFFICIENT_FUNDS.value, 30),
    (FailureReason.AUTHENTICATION_TIMEOUT.value, 20),
    (FailureReason.BANK_DECLINE.value, 18),
    (FailureReason.CARD_EXPIRED.value, 8),
    (FailureReason.INVALID_CARD_DETAILS.value, 7),
    (FailureReason.NETWORK_ERROR.value, 9),
    (FailureReason.RISK_BLOCKED.value, 4),
    (FailureReason.CUSTOMER_DROPOFF.value, 4),
]

GATEWAY_CODE_BY_REASON = {
    FailureReason.INSUFFICIENT_FUNDS: "insufficient_funds",
    FailureReason.AUTHENTICATION_TIMEOUT: "otp_timeout",
    FailureReason.BANK_DECLINE: "gateway_declined",
    FailureReason.INVALID_CARD_DETAILS: "invalid_card_details",
    FailureReason.CARD_EXPIRED: "card_expired",
    FailureReason.NETWORK_ERROR: "gateway_timed_out",
    FailureReason.RISK_BLOCKED: "risk_blocked",
    FailureReason.CUSTOMER_DROPOFF: "customer_abandoned",
}


def _weighted_failure(rng: random.Random) -> str:
    population, weights = zip(*FAILURE_DISTRIBUTION)
    return rng.choices(population, weights=weights, k=1)[0]


def random_customer(rng: random.Random) -> Dict[str, str]:
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    digits = "".join(rng.choices(string.digits, k=10))
    phone = normalize_indian_phone(f"{rng.choice(['6', '7', '8', '9'])}{digits[1:]}")
    return {
        "name": f"{first} {last}",
        "email": f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@example.com",
        "phone": phone,
    }


def random_amount_inr(rng: random.Random) -> float:
    # Long-tail: most transactions small, few large
    bucket = rng.random()
    if bucket < 0.60:
        return round(rng.uniform(199, 2500), 2)
    if bucket < 0.90:
        return round(rng.uniform(2500, 15000), 2)
    if bucket < 0.99:
        return round(rng.uniform(15000, 60000), 2)
    return round(rng.uniform(60000, 250000), 2)


def make_failed_payment(
    *,
    seed: Optional[int] = None,
    age_minutes: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a single payment payload matching PaymentIngestRequest."""
    rng = random.Random(seed)
    customer = random_customer(rng)
    failure_reason = _weighted_failure(rng)
    method = rng.choice(list(PaymentMethod))
    created = utcnow() - timedelta(minutes=age_minutes)

    payload: Dict[str, Any] = {
        "order_id": f"order_{''.join(rng.choices(string.ascii_lowercase + string.digits, k=14))}",
        "gateway_payment_id": f"pay_{''.join(rng.choices(string.ascii_uppercase + string.digits, k=14))}",
        "customer": customer,
        "amount": random_amount_inr(rng),
        "currency": "INR",
        "method": method.value,
        "status": PaymentStatus.FAILED.value,
        "failure_reason_code": GATEWAY_CODE_BY_REASON.get(FailureReason(failure_reason), failure_reason),
        "error_description": f"{failure_reason.replace('_', ' ').title()} at {rng.choice(BANKS)}",
        "attempt_number": rng.randint(1, 3),
        "metadata": {"source": "mock_data", "age_minutes": str(age_minutes)},
    }
    payload.update(overrides)
    return payload


def generate_payment_batch(
    count: int,
    *,
    seed: Optional[int] = None,
    success_ratio: float = 0.35,
) -> List[Dict[str, Any]]:
    """Generate a batch; ``success_ratio`` of payments will be captured
    (healthy traffic), the rest failed payments needing recovery."""
    rng = random.Random(seed)
    batch: List[Dict[str, Any]] = []
    for index in range(count):
        age = rng.randint(1, 72 * 60)  # up to 72h old
        payment = make_failed_payment(seed=rng.randint(0, 10**9), age_minutes=age)
        if rng.random() < success_ratio:
            payment["status"] = PaymentStatus.CAPTURED.value
            payment["failure_reason_code"] = None
            payment["error_description"] = None
        payment["metadata"]["batch_index"] = str(index)
        batch.append(payment)
    return batch
