"""Weekly recovery-model retraining, staging, promotion, and rollback."""

from __future__ import annotations

import csv
import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_sample_weight

from app.database.models import MLModelVersion, RecoveryRecord
from app.models.payment import utcnow

logger = logging.getLogger(__name__)
OUTCOME_LABELS = ("failed", "partial", "full")
FEATURES = ("amount_inr", "customer_tenure_years", "failure_count", "retry_attempts", "hour_utc", "is_peak_hour", "contact_on_weekend", "contact_in_evening", "is_business")


@dataclass
class RetrainingResult:
    version: str
    status: str
    holdout_f1: float
    current_f1: float | None
    event: str


def _vector(row: dict[str, Any]) -> list[float]:
    return [
        float(row.get("amount_inr", 0)),
        float(row.get("customer_tenure_years", 0)),
        float(row.get("failure_count", 0)),
        float(row.get("retry_attempts", 0)),
        float(row.get("hour_utc", 0)),
        float(row.get("is_peak_hour", 0)),
        float(row.get("contact_on_weekend", 0)),
        float(row.get("contact_in_evening", 0)),
        float(row.get("is_business", row.get("customer_type") == "business")),
    ]


class RetrainingPipeline:
    """Coordinates weekly training and an on-disk model registry."""

    def __init__(self, model_dir: str | Path = "models", baseline_path: str | Path = "data/recovery_training.csv") -> None:
        self.model_dir = Path(model_dir)
        self.baseline_path = Path(baseline_path)
        self.registry_dir = self.model_dir / "registry"
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.registry_dir / "retraining_events.jsonl"
        self.current_pointer = self.registry_dir / "production.json"
        self.staging_pointer = self.registry_dir / "staging.json"

    def _log(self, event: str, **details: Any) -> None:
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **details}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        logger.info("model_retraining.%s", event, extra=details)

    def _load_baseline(self) -> list[dict[str, Any]]:
        with self.baseline_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["is_business"] = row.get("customer_type") == "business"
        return rows

    @staticmethod
    def _recent_outcomes(db) -> list[dict[str, Any]]:
        cutoff = utcnow() - timedelta(days=7)
        records = db.query(RecoveryRecord).filter(RecoveryRecord.created_at >= cutoff).all()
        rows = []
        for record in records:
            recovered = record.recovered_amount_paise
            original = record.expected_amount_paise
            label = "failed" if recovered <= 0 else "full" if recovered >= original else "partial"
            rows.append({
                "amount_inr": original / 100,
                "customer_tenure_years": 0,
                "failure_count": record.attempts,
                "retry_attempts": record.attempts,
                "hour_utc": record.created_at.hour,
                "is_peak_hour": int(record.created_at.hour in {8, 9, 10, 17, 18, 19, 20}),
                "contact_on_weekend": int(record.created_at.weekday() >= 5),
                "contact_in_evening": int(record.created_at.hour in {17, 18, 19, 20, 21, 22}),
                "is_business": False,
                "recovery_success": label,
            })
        return rows

    def _train(self, rows: Iterable[dict[str, Any]], seed: int):
        from xgboost import XGBClassifier

        materialized = list(rows)
        x = np.array([_vector(row) for row in materialized], dtype=float)
        y = np.array([OUTCOME_LABELS.index(str(row["recovery_success"])) for row in materialized])
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=0.2, random_state=seed, stratify=y
        )
        model = XGBClassifier(
            objective="multi:softprob", num_class=len(OUTCOME_LABELS),
            n_estimators=120, max_depth=4, learning_rate=0.08,
            eval_metric="mlogloss", random_state=seed, n_jobs=1,
        )
        model.fit(x_train, y_train, sample_weight=compute_sample_weight("balanced", y_train))
        score = float(f1_score(y_test, model.predict(x_test), average="macro"))
        return model, score

    def _metadata(self, pointer: Path) -> dict[str, Any] | None:
        if not pointer.exists():
            return None
        return json.loads(pointer.read_text(encoding="utf-8"))

    def _save_metadata(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def promote_staging(self, *, now: datetime | None = None) -> RetrainingResult | None:
        staging = self._metadata(self.staging_pointer)
        if not staging:
            return None
        now = now or datetime.now(timezone.utc)
        staged_at = datetime.fromisoformat(staging["staged_at"])
        if now < staged_at + timedelta(hours=24):
            return None
        current = self._metadata(self.current_pointer)
        if current and staging["holdout_f1"] < current["holdout_f1"]:
            self._log("rollback", version=staging["version"], reason="staging_performance_degraded", previous_version=current["version"])
            self.staging_pointer.unlink(missing_ok=True)
            return RetrainingResult(staging["version"], "rolled_back", staging["holdout_f1"], current["holdout_f1"], "rollback")
        shutil.copy2(self.registry_dir / staging["artifact"], self.model_dir / "recovery_outcome_model.joblib")
        self._save_metadata(self.current_pointer, staging)
        self.staging_pointer.unlink(missing_ok=True)
        self._log("promote", version=staging["version"], holdout_f1=staging["holdout_f1"])
        return RetrainingResult(staging["version"], "production", staging["holdout_f1"], current["holdout_f1"] if current else None, "promote")

    def run(self, db=None, *, seed: int = 42) -> RetrainingResult:
        """Train, evaluate, and stage a candidate; promotion occurs after 24h."""
        self._log("started", baseline=str(self.baseline_path), lookback_days=7)
        rows = self._load_baseline()
        recent = self._recent_outcomes(db) if db is not None else []
        rows.extend(recent)
        self._log("data_combined", baseline_rows=len(rows) - len(recent), recent_rows=len(recent), total_rows=len(rows))
        if len({str(row["recovery_success"]) for row in rows}) < 3:
            raise ValueError("retraining requires failed, partial, and full outcomes")
        model, score = self._train(rows, seed)
        current = self._metadata(self.current_pointer)
        version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self._log("evaluated", version=version, holdout_f1=score, current_f1=current["holdout_f1"] if current else None)
        if current and score <= current["holdout_f1"]:
            self._log("rollback", version=version, reason="holdout_performance_not_better", current_version=current["version"])
            return RetrainingResult(version, "rolled_back", score, current["holdout_f1"], "rollback")
        import joblib
        artifact = f"recovery_outcome_model-{version}.joblib"
        joblib.dump(model, self.registry_dir / artifact)
        metadata = {"version": version, "artifact": artifact, "holdout_f1": score, "staged_at": datetime.now(timezone.utc).isoformat(), "labels": OUTCOME_LABELS, "features": FEATURES}
        self._save_metadata(self.staging_pointer, metadata)
        if db is not None:
            db.add(MLModelVersion(model_name="recovery_outcome", version=version, accuracy=score, f1_score=score))
            db.commit()
        self._log("staged", version=version, holdout_f1=score, promotion_after_hours=24)
        return RetrainingResult(version, "staged", score, current["holdout_f1"] if current else None, "stage")
