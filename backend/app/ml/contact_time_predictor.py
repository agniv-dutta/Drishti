"""Predict customer-local contact windows for recovery outreach."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ContactTimePrediction:
    """Best candidate window and its estimated recovery probability."""

    hour: int
    success_probability: float
    timezone: str
    source: str = "profile_fallback"


class ContactTimePredictor:
    """Empirical time-of-day predictor with a safe cold-start fallback.

    ``train`` accepts dictionaries from the recovery-attempt dataset. A row is
    successful when its recovery_success value is 1, true, full, or partial.
    """

    MIN_SUCCESS_PROBABILITY = 0.30
    HIGH_SUCCESS_PROBABILITY = 0.60
    _DEFAULT_PROFILE = {
        "professional": {21: 0.72, 13: 0.65, 7: 0.15, 16: 0.22},
        "housewife": {11: 0.68, 12: 0.68, 7: 0.20, 19: 0.20},
        "default": {13: 0.55, 21: 0.55, 11: 0.50, 7: 0.20},
    }

    def __init__(self) -> None:
        self._observations: Dict[tuple[str, int], List[int]] = {}

    def train(self, rows: Iterable[Dict[str, Any]]) -> "ContactTimePredictor":
        for row in rows:
            hour = self._hour(row.get("time_of_day", row.get("hour_utc", 0)))
            segment = self._segment(row)
            key = (segment, hour)
            self._observations.setdefault(key, []).append(
                int(self._is_success(row.get("recovery_success")))
            )
        return self

    def train_csv(self, path: str | Path) -> "ContactTimePredictor":
        with Path(path).open(newline="", encoding="utf-8") as handle:
            self.train(csv.DictReader(handle))
        return self

    def predict(self, features: Dict[str, Any]) -> ContactTimePrediction:
        segment = self._segment(features)
        timezone_name = str(features.get("location_timezone") or "Asia/Kolkata")
        try:
            ZoneInfo(timezone_name)
        except Exception:
            timezone_name = "Asia/Kolkata"

        candidates = range(24)
        scored = [(hour, self._score(segment, hour)) for hour in candidates]
        best_hour, probability = max(scored, key=lambda item: (item[1], -item[0]))
        source = "historical" if any(key[0] == segment for key in self._observations) else "profile_fallback"
        return ContactTimePrediction(best_hour, round(probability, 4), timezone_name, source)

    def scheduled_at(
        self,
        prediction: ContactTimePrediction,
        now: Optional[datetime] = None,
        immediate: bool = False,
    ) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        local_now = current.astimezone(ZoneInfo(prediction.timezone))
        if immediate:
            return current
        target = local_now.replace(hour=prediction.hour, minute=0, second=0, microsecond=0)
        if target <= local_now:
            target += timedelta(days=1)
        return target.astimezone(timezone.utc)

    def _score(self, segment: str, hour: int) -> float:
        observations = self._observations.get((segment, hour))
        if observations:
            return (sum(observations) + 1) / (len(observations) + 2)
        return self._DEFAULT_PROFILE.get(segment, self._DEFAULT_PROFILE["default"]).get(hour, 0.35)

    @staticmethod
    def _hour(value: Any) -> int:
        try:
            return int(value.hour) if hasattr(value, "hour") else int(str(value).split(":")[0]) % 24
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _segment(features: Dict[str, Any]) -> str:
        value = str(features.get("customer_segment") or features.get("customer_type") or "default").lower()
        if any(term in value for term in ("professional", "business", "working")):
            return "professional"
        if any(term in value for term in ("housewife", "homemaker")):
            return "housewife"
        return "default"

    @staticmethod
    def _is_success(value: Any) -> bool:
        return value is True or str(value).lower() in {"1", "true", "yes", "full", "partial", "success", "succeeded"}


_default_predictor = ContactTimePredictor()
_training_data = Path(__file__).resolve().parents[2] / "data" / "recovery_training.csv"
if _training_data.exists():
    try:
        _default_predictor.train_csv(_training_data)
    except (OSError, csv.Error):
        pass


def get_contact_time_predictor() -> ContactTimePredictor:
    return _default_predictor