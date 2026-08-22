"""Recovery metrics derived from persisted recovery attempts."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy.orm import Session

from app.database.models import RecoveryRecord
from app.models.payment import utcnow


class MetricsCollector:
    """Calculate business metrics and expose the same values to Prometheus."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.recovery_rate = Gauge(
            "drishti_recovery_rate", "Recovered payments divided by attempted payments", registry=self.registry
        )
        self.average_recovery_percent = Gauge(
            "drishti_average_recovery_percent", "Recovered amount divided by original amount", registry=self.registry
        )
        self.cost_per_recovery = Gauge(
            "drishti_cost_per_recovery_inr", "Channel cost divided by recovered payments", registry=self.registry
        )
        self.false_positive_rate = Gauge(
            "drishti_false_positive_rate", "Negative outcomes divided by recommended actions", registry=self.registry
        )
        self.model_drift = Gauge(
            "drishti_model_drift_score", "Mean absolute error against the baseline", registry=self.registry
        )
        self.channel_cost = Gauge(
            "drishti_channel_cost_inr", "Recovery cost by channel", ["channel"], registry=self.registry
        )
        self.strategy_recoveries = Gauge(
            "drishti_strategy_recoveries", "Recovered payments by strategy", ["strategy"], registry=self.registry
        )

    @staticmethod
    def model_drift_score(current_week: Iterable[float], baseline: Iterable[float]) -> float:
        """Return MAE between current and baseline model outputs."""
        current = list(current_week)
        reference = list(baseline)
        if len(current) != len(reference):
            raise ValueError("current_week and baseline must have equal lengths")
        if not current:
            return 0.0
        return sum(abs(float(actual) - float(expected)) for actual, expected in zip(current, reference)) / len(current)

    def collect(
        self,
        db: Session,
        period_days: int = 30,
        *,
        current_predictions: Iterable[float] | None = None,
        baseline_predictions: Iterable[float] | None = None,
    ) -> dict[str, Any]:
        cutoff = utcnow() - timedelta(days=period_days)
        records = db.query(RecoveryRecord).filter(RecoveryRecord.created_at >= cutoff).all()
        attempted = [record for record in records if record.attempts > 0]
        recovered = [record for record in attempted if record.recovered_amount_paise > 0]
        original_amount = sum(record.expected_amount_paise for record in records)
        recovered_amount = sum(record.recovered_amount_paise for record in records)
        total_cost = sum(record.cost_paise for record in records)
        recommended_actions = 0
        negative_outcomes = 0
        channel_costs: dict[str, int] = {}
        strategy_recoveries: dict[str, int] = {}
        for record in records:
            if record.recovered_amount_paise > 0:
                strategy_recoveries[record.strategy] = strategy_recoveries.get(record.strategy, 0) + 1
            for outcome in (record.result_json or {}).get("outcomes", []):
                if outcome.get("status") == "skipped":
                    continue
                recommended_actions += 1
                if outcome.get("status") in {"failed", "rejected"}:
                    negative_outcomes += 1
                channel = outcome.get("channel", "unknown")
                channel_costs[channel] = channel_costs.get(channel, 0) + int(outcome.get("cost_incurred_paise", 0))

        drift = self.model_drift_score(current_predictions or [], baseline_predictions or []) if current_predictions is not None and baseline_predictions is not None else 0.0
        values = {
            "period_days": period_days,
            "total_payments_attempted": len(attempted),
            "payments_recovered": len(recovered),
            "recovery_rate": len(recovered) / len(attempted) if attempted else 0.0,
            "average_recovery_percent": recovered_amount / original_amount * 100 if original_amount else 0.0,
            "cost_per_recovery_inr": total_cost / 100 / len(recovered) if recovered else 0.0,
            "false_positive_rate": negative_outcomes / recommended_actions if recommended_actions else 0.0,
            "model_drift_score": drift,
            "channel_costs_inr": {channel: cost / 100 for channel, cost in channel_costs.items()},
            "strategy_recoveries": strategy_recoveries,
        }
        self.recovery_rate.set(values["recovery_rate"])
        self.average_recovery_percent.set(values["average_recovery_percent"])
        self.cost_per_recovery.set(values["cost_per_recovery_inr"])
        self.false_positive_rate.set(values["false_positive_rate"])
        self.model_drift.set(drift)
        for channel, cost in values["channel_costs_inr"].items():
            self.channel_cost.labels(channel=channel).set(cost)
        for strategy, count in strategy_recoveries.items():
            self.strategy_recoveries.labels(strategy=strategy).set(count)
        return values

    def prometheus_payload(self) -> bytes:
        return generate_latest(self.registry)
