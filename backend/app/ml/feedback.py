"""Feedback loop - the system learns from what worked.

Every executed recovery attempt is logged as a ``LearningEventRecord`` with
strategy, customer response, time-to-recovery, money recovered and an inferred
happiness score. Weekly aggregation ranks strategies per failure_reason,
customer_segment, region and time_of_day, and renders a dynamic prompt block
("Based on N recovery attempts this week: ...") that is injected into agent
prompts so recommendations continuously improve without model retraining.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cache.redis_client import get_cache
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.database.models import LearningEventRecord
from app.models.payment import utcnow
from app.models.recovery import ExecutionResult, RecoveryPlan

logger = get_logger("drishti.learning")


class CustomerResponse(str, Enum):
    SUCCESS = "success"
    NO_RESPONSE = "no_response"
    OPTED_OUT = "opted_out"
    COMPLAINED = "complained"


# Tactic labels used in aggregates / dynamic prompts (retry / SMS / call / ...).
TACTIC_LABELS = {
    "smart_retry": "retry",
    "nudge_digital": "SMS",
    "high_touch_voice": "call",
    "crm_human_escalation": "escalate",
    "write_off": "write_off",
}

_DIMENSIONS = ("failure_reason", "customer_segment", "region", "time_of_day")

_OPTOUT_MARKERS = ("opt-out", "opted out", "unsubscribe", "dnd", "do not disturb", "stop ")
_COMPLAIN_MARKERS = ("complain", "angry", "frustrat", "harass", "escalated to", "refund threat")

_LEARNING_CACHE_KEY = "learning:weekly:v1"
_LEARNING_CACHE_TTL = 3600  # 1h


def time_bucket(dt) -> str:
    """UTC day-part bucket for time_of_day analytics."""
    hour = dt.hour
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def classify_response(result: ExecutionResult, meta: Dict[str, Any]) -> CustomerResponse:
    """Derive customer response from execution outcome + explicit signals."""
    override = str(meta.get("customer_response", "")).strip().lower()
    if override:
        try:
            return CustomerResponse(override)
        except ValueError:
            pass

    if result.success:
        return CustomerResponse.SUCCESS

    text = " ".join((o.detail or "").lower() for o in result.outcomes)
    if any(marker in text for marker in _COMPLAIN_MARKERS):
        return CustomerResponse.COMPLAINED
    if any(marker in text for marker in _OPTOUT_MARKERS):
        return CustomerResponse.OPTED_OUT
    return CustomerResponse.NO_RESPONSE


def infer_happiness(response: CustomerResponse, support_tickets: int = 0) -> float:
    """Happiness in [0,1]; support tickets drag it down regardless of outcome."""
    base = {
        CustomerResponse.SUCCESS: 0.9,
        CustomerResponse.NO_RESPONSE: 0.5,
        CustomerResponse.OPTED_OUT: 0.3,
        CustomerResponse.COMPLAINED: 0.1,
    }[response]
    score = base - 0.05 * max(support_tickets, 0)
    return round(min(max(score, 0.0), 1.0), 2)


class FeedbackLoop:
    """Writes attempt-level events and turns them into weekly strategy priors."""

    # ------------------------------------------------------------------
    # logging
    # ------------------------------------------------------------------
    def log_attempt(
        self,
        db: Session,
        *,
        recovery_id: str,
        plan: RecoveryPlan,
        result: ExecutionResult,
        payment_id: str,
        amount_paise: int,
        failure_reason: Optional[str],
        meta: Dict[str, Any],
        payment_created_at=None,
    ) -> LearningEventRecord:
        response = classify_response(result, meta)
        tickets = int(meta.get("support_tickets", 0) or 0)

        winning_channel = None
        for outcome in sorted(result.outcomes, key=lambda o: o.sequence):
            if outcome.recovered_amount_paise > 0:
                winning_channel = outcome.channel.value
                break
        if winning_channel is None:
            for outcome in sorted(result.outcomes, key=lambda o: o.sequence):
                if outcome.status.value == "succeeded":
                    winning_channel = outcome.channel.value
                    break
        winning_channel = winning_channel or (plan.steps[0].channel.value if plan.steps else "none")

        completed_at = result.completed_at or utcnow()
        started_at = plan.created_at or payment_created_at or completed_at
        ttr_seconds = max(int((completed_at - started_at).total_seconds()), 0)

        event = LearningEventRecord(
            payment_id=payment_id,
            recovery_id=recovery_id,
            strategy=plan.strategy.value,
            channel=winning_channel,
            customer_response=response.value,
            time_to_recovery_seconds=ttr_seconds,
            amount_paise=amount_paise,
            recovered_paise=result.recovered_amount_paise,
            failure_reason=failure_reason or "unknown",
            customer_segment=str(meta.get("customer_segment", "new")),
            region=str(meta.get("region", "unknown")),
            time_of_day=time_bucket(payment_created_at or completed_at),
            happiness_score=infer_happiness(response, tickets),
        )
        db.add(event)
        db.flush()
        logger.info(
            "learning.attempt_logged",
            payment_id=payment_id,
            strategy=event.strategy,
            channel=event.channel,
            response=event.customer_response,
            recovered_paise=event.recovered_paise,
            happiness=event.happiness_score,
        )
        return event

    # ------------------------------------------------------------------
    # weekly aggregation
    # ------------------------------------------------------------------
    def weekly_aggregates(self, db: Session, days: int = 7, min_samples: int = 5) -> Dict[str, Any]:
        cutoff = utcnow() - timedelta(days=days)
        rows = db.execute(
            select(
                LearningEventRecord.failure_reason,
                LearningEventRecord.customer_segment,
                LearningEventRecord.region,
                LearningEventRecord.time_of_day,
                LearningEventRecord.strategy,
                LearningEventRecord.customer_response,
                LearningEventRecord.time_to_recovery_seconds,
                LearningEventRecord.amount_paise,
                LearningEventRecord.recovered_paise,
            ).where(LearningEventRecord.created_at >= cutoff)
        ).all()

        totals = {"attempts": len(rows), "successes": 0}
        buckets: Dict[str, Dict[tuple, List[tuple]]] = {dim: {} for dim in _DIMENSIONS}

        for row in rows:
            (
                failure_reason,
                segment,
                region,
                tod,
                strategy,
                response,
                ttr,
                amount,
                recovered,
            ) = row
            succeeded = response == CustomerResponse.SUCCESS.value
            if succeeded:
                totals["successes"] += 1
            values = {
                "failure_reason": failure_reason or "unknown",
                "customer_segment": segment or "unknown",
                "region": region or "unknown",
                "time_of_day": tod or "unknown",
            }
            for dim, value in values.items():
                buckets[dim].setdefault((value, strategy), []).append(
                    (succeeded, ttr or 0, recovered or 0, amount or 0)
                )

        aggregate: Dict[str, Any] = {
            "window_days": days,
            "min_samples": min_samples,
            "total_attempts": totals["attempts"],
            "overall_success_rate": round(totals["successes"] / totals["attempts"], 4)
            if totals["attempts"]
            else 0.0,
            "generated_at": utcnow().isoformat(),
        }
        for dim, groups in buckets.items():
            dim_result: Dict[str, Any] = {}
            by_value: Dict[str, List[Dict[str, Any]]] = {}
            for (value, strategy), entries in groups.items():
                attempts = len(entries)
                successes = sum(1 for e in entries if e[0])
                stats = {
                    "strategy": strategy,
                    "tactic": TACTIC_LABELS.get(strategy, strategy),
                    "attempts": attempts,
                    "successes": successes,
                    "success_rate": round(successes / attempts, 4),
                    "avg_time_to_recovery_s": round(sum(e[1] for e in entries) / attempts),
                    "recovered_ratio": round(sum(e[2] for e in entries) / max(sum(e[3] for e in entries), 1), 4),
                }
                by_value.setdefault(value, []).append(stats)

            for value, rankings in by_value.items():
                qualified = [r for r in rankings if r["attempts"] >= min_samples]
                ranked = sorted(qualified, key=lambda r: (r["success_rate"], r["attempts"]), reverse=True)
                dim_result[value] = {
                    "best_strategy": ranked[0]["tactic"] if ranked else None,
                    "ranking": ranked,
                    "insufficient_data": [r["tactic"] for r in rankings if r not in qualified],
                }
            aggregate[f"by_{dim}"] = dim_result
        return aggregate

    # ------------------------------------------------------------------
    # dynamic prompt rendering
    # ------------------------------------------------------------------
    def format_learning_prompt(self, aggregates: Dict[str, Any], max_lines: int = 8) -> str:
        total = aggregates.get("total_attempts", 0)
        lines: List[str] = []
        by_reason = aggregates.get("by_failure_reason", {})
        for reason, info in list(by_reason.items())[:max_lines]:
            ranking = info.get("ranking") or []
            if not ranking:
                continue
            parts = " > ".join(
                f"{r['tactic']} ({round(r['success_rate'] * 100)}% success)" for r in ranking[:3]
            )
            lines.append(f"- For {reason}: {parts}")

        if not lines:
            return ""
        return (
            f"Based on {total} recovery attempts this week:\n"
            + "\n".join(lines)
            + "\nPrioritize high-success strategies in your recommendations."
        )


_feedback_loop: Optional[FeedbackLoop] = None


def get_feedback_loop() -> FeedbackLoop:
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = FeedbackLoop()
    return _feedback_loop


async def get_learning_snapshot() -> Dict[str, Any]:
    """Cached weekly aggregates; empty dict when nothing logged yet."""
    cache = await get_cache()
    cached = await cache.get_json(_LEARNING_CACHE_KEY)
    if cached:
        return cached

    from app.database.session import get_session_factory

    aggregates: Dict[str, Any] = {}
    try:
        with get_session_factory()() as db:
            aggregates = get_feedback_loop().weekly_aggregates(db, days=7, min_samples=5)
    except Exception as exc:  # noqa: BLE001 - learning must never break the pipeline
        logger.warning("learning.snapshot_failed", error=str(exc))
        return {}

    await cache.set_json(_LEARNING_CACHE_KEY, aggregates, ttl=_LEARNING_CACHE_TTL)
    return aggregates


async def build_learned_context() -> str:
    """Dynamic prompt block for agent prompts ('' when insufficient data)."""
    snapshot = await get_learning_snapshot()
    if not snapshot or snapshot.get("total_attempts", 0) < 10:
        return ""
    return get_feedback_loop().format_learning_prompt(snapshot)
