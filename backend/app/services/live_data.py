"""Live data generator for real-time dashboard metrics.

Generates realistic synthetic payment and recovery data that updates
continuously in the background.  Existing DB-backed endpoints are NOT
replaced — this module only feeds new /live-* endpoints.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


_FAILURE_REASONS = {
    "insufficient_funds": 0.34,
    "declined_by_issuer": 0.22,
    "expired_card": 0.15,
    "3ds_timeout": 0.12,
    "lost_card": 0.08,
    "fraud_block": 0.09,
}

_STRATEGIES = ["smart_retry", "nudge_digital", "high_touch_voice", "offer_discount", "escalate"]
_SEGMENTS = ["new", "retained", "high_value"]
_STATUSES_WEIGHTED = ["recovered", "failed", "in_progress", "escalated"]
_STATUS_WEIGHTS = [0.45, 0.25, 0.20, 0.10]
_AMOUNTS = [500, 1000, 2000, 5000, 10000, 25000]

_AGENT_NAMES = [
    "PaymentAnalyzer",
    "StrategySelector",
    "ExecutorAgent",
    "ConsensusAgent",
    "AuditSupervisor",
]

_AGENT_ROLES = {
    "PaymentAnalyzer": "Failure cause detection & risk scoring",
    "StrategySelector": "Recovery strategy selection & A/B testing",
    "ExecutorAgent": "Recovery workflow execution & channel dispatch",
    "ConsensusAgent": "Multi-agent confidence consensus & gating",
    "AuditSupervisor": "Compliance gate & audit trail recording",
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_payment(batch_ts: float, index: int) -> Dict[str, Any]:
    failure_reason = random.choices(
        list(_FAILURE_REASONS.keys()),
        weights=list(_FAILURE_REASONS.values()),
    )[0]
    amount = random.choice(_AMOUNTS)
    strategy = random.choice(_STRATEGIES)
    status = random.choices(_STATUSES_WEIGHTED, weights=_STATUS_WEIGHTS)[0]
    recovered_amount = amount if status == "recovered" else 0
    return {
        "id": f"pay_{batch_ts}_{index:04d}",
        "amount": amount,
        "failure_reason": failure_reason,
        "customer_segment": random.choice(_SEGMENTS),
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=random.randint(0, 24))).isoformat(),
        "strategy_used": strategy,
        "status": status,
        "money_recovered": recovered_amount,
        "confidence": round(random.uniform(0.45, 0.95), 2),
        "ai_model_confidence": round(random.uniform(0.50, 0.95), 2),
    }


class LiveDataGenerator:
    """Singleton that generates realistic payment & recovery data in the background."""

    def __init__(self) -> None:
        self._payments: List[Dict[str, Any]] = []
        self._task: asyncio.Task | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Kick off the background generation loop (call once at startup)."""
        if self._started:
            return
        self._started = True
        self._seed_batch(50)
        self._task = asyncio.get_event_loop().create_task(self._loop())

    async def stop(self) -> None:
        """Stop the background generation loop during application shutdown."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self._started = False

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            self._add_single()
            # Trim to last 500
            if len(self._payments) > 500:
                self._payments = self._payments[-500:]

    # ------------------------------------------------------------------
    # Data generation
    # ------------------------------------------------------------------

    def _seed_batch(self, count: int = 50) -> None:
        batch_ts = datetime.now(timezone.utc).timestamp()
        self._payments = [_make_payment(batch_ts, i) for i in range(count)]

    def _add_single(self) -> None:
        ts = datetime.now(timezone.utc).timestamp()
        self._payments.append(_make_payment(ts, len(self._payments)))

    # ------------------------------------------------------------------
    # Public query helpers
    # ------------------------------------------------------------------

    @property
    def payments(self) -> List[Dict[str, Any]]:
        return list(self._payments)

    def get_live_metrics(self) -> Dict[str, Any]:
        """Return aggregate KPI metrics derived from the live payment set."""
        total = len(self._payments)
        if total == 0:
            return self._empty_metrics()

        recovered = [p for p in self._payments if p["status"] == "recovered"]
        failed = [p for p in self._payments if p["status"] == "failed"]
        in_progress = [p for p in self._payments if p["status"] == "in_progress"]
        escalated = [p for p in self._payments if p["status"] == "escalated"]

        total_recovered = sum(p["money_recovered"] for p in recovered)
        recovery_rate = round(len(recovered) / total * 100, 1)
        avg_cost = round(total_recovered * 0.015 / max(len(recovered), 1), 0)

        # Strategy performance
        strategy_perf: Dict[str, Dict[str, Any]] = {}
        for strat in _STRATEGIES:
            strat_payments = [p for p in self._payments if p["strategy_used"] == strat]
            strat_recovered = [p for p in strat_payments if p["status"] == "recovered"]
            strategy_perf[strat] = {
                "success_rate": round(len(strat_recovered) / max(len(strat_payments), 1) * 100),
                "total_used": len(strat_payments),
                "recovered_amount": sum(p["money_recovered"] for p in strat_recovered),
            }

        # Failure reason breakdown
        failure_breakdown: Dict[str, int] = {}
        for p in failed:
            reason = p["failure_reason"]
            failure_breakdown[reason] = failure_breakdown.get(reason, 0) + 1

        return {
            "total_payments": total,
            "recovery_rate": recovery_rate,
            "total_recovered": total_recovered,
            "avg_cost_per_recovery": avg_cost,
            "recovered_count": len(recovered),
            "failed_count": len(failed),
            "in_progress_count": len(in_progress),
            "escalated_count": len(escalated),
            "strategy_performance": strategy_perf,
            "failure_breakdown": failure_breakdown,
            "generated_at": _ts(),
        }

    def get_agent_status(self) -> Dict[str, Any]:
        """Return live agent processing status."""
        agents = []
        total = len(self._payments)
        for name in _AGENT_NAMES:
            processed = random.randint(max(1, total - 15), total)
            progress = min(100, round(processed / total * 100))
            queue_depth = max(0, total - processed)
            agents.append({
                "name": name,
                "label": _AGENT_ROLES[name],
                "progress": progress,
                "status": "processing" if queue_depth > 0 else "idle",
                "queue": queue_depth,
                "processed": processed,
                "total": total,
                "latency_ms": round(random.uniform(0.8, 3.2), 1),
            })

        recovered = len([p for p in self._payments if p["status"] == "recovered"])
        failed = len([p for p in self._payments if p["status"] == "failed"])
        return {
            "generated_at": _ts(),
            "pipeline": {
                "total": total,
                "recovered": recovered,
                "failed": failed,
                "recovery_rate": round(recovered / max(total, 1) * 100, 1),
            },
            "agents": agents,
        }

    def get_payments_list(self, limit: int = 50, status: str | None = None) -> Dict[str, Any]:
        """Return a slice of live payments."""
        payments = self._payments
        if status:
            payments = [p for p in payments if p["status"] == status]
        return {
            "total": len(payments),
            "payments": payments[-limit:],
            "timestamp": _ts(),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _empty_metrics() -> Dict[str, Any]:
        return {
            "total_payments": 0,
            "recovery_rate": 0,
            "total_recovered": 0,
            "avg_cost_per_recovery": 0,
            "recovered_count": 0,
            "failed_count": 0,
            "in_progress_count": 0,
            "escalated_count": 0,
            "strategy_performance": {},
            "failure_breakdown": {},
            "generated_at": _ts(),
        }


# Module-level singleton
live_data = LiveDataGenerator()
