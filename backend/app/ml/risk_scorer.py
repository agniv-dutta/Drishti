"""Recovery-risk scoring.

Heuristic model out of the box; transparently upgrades to a trained AutoML /
sklearn artifact (joblib) when ``RISK_MODEL_PATH`` points at a pickled
classifier exposing ``predict_proba``. See scripts/train_automl.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

BANDS: Tuple[Tuple[str, float, float], ...] = (
    ("low", 0.00, 0.35),
    ("medium", 0.35, 0.65),
    ("high", 0.65, 0.85),
    ("critical", 0.85, 1.01),
)

# Baseline P(recovery success | failure reason), tuned on Indian gateway data.
_BASE_BY_REASON: Dict[str, float] = {
    "network_error": 0.78,            # our side failed -> retry usually works
    "insufficient_funds": 0.62,       # payday retry converts well
    "authentication_timeout": 0.55,   # OTP abandonment, nudge works
    "customer_dropoff": 0.45,
    "bank_decline": 0.34,
    "unknown": 0.40,
    "card_expired": 0.28,             # needs customer to update card
    "invalid_card_details": 0.24,
    "risk_blocked": 0.12,
}


class RiskScorer:
    """Scores P(successful recovery) in [0, 1]."""

    def __init__(self, model_path: Optional[str] = None):
        self._model = None
        self._model_path = model_path
        if model_path and Path(model_path).exists():
            self._load_model(model_path)

    def _load_model(self, path: str) -> None:
        try:
            import joblib

            self._model = joblib.load(path)
            logger.info("risk_scorer.model_loaded", path=path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk_scorer.model_load_failed", path=path, error=str(exc))

    @property
    def using_ml_model(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------
    def score(self, features: Dict[str, float]) -> Tuple[float, str, Dict[str, float]]:
        """Return (score, band, contributions)."""
        if self._model is not None:
            try:
                from app.ml.data_preprocessor import FEATURE_NAMES

                row = [features[name] for name in FEATURE_NAMES]
                proba = float(self._model.predict_proba([row])[0][1])
                _, band_name = band_of(proba)
                return round(proba, 4), band_name, {"ml_model": round(proba, 4)}
            except Exception as exc:  # noqa: BLE001
                logger.warning("risk_scorer.ml_fallback_heuristic", error=str(exc))

        score, contributions = self._heuristic(features)
        _, band_name = band_of(score)
        return score, band_name, contributions

    def _heuristic(self, features: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
        contributions: Dict[str, float] = {}

        reason_score = 0.40
        for name in features:
            if name.startswith("reason_") and features[name] == 1.0:
                reason = name.removeprefix("reason_")
                reason_score = _BASE_BY_REASON.get(reason, 0.40)
                contributions[f"reason:{reason}"] = reason_score
                break

        method_modifier = 0.0
        if features.get("method_upi") == 1.0:
            method_modifier += 0.05   # UPI collect retries convert well
        elif features.get("method_card") == 1.0:
            method_modifier += 0.02
        if method_modifier:
            contributions["method"] = method_modifier

        attempts = int(features.get("attempt_number", 1))
        attempt_modifier = -0.07 * max(attempts - 1, 0)
        if attempt_modifier:
            contributions["fatigue"] = attempt_modifier

        hour = features.get("hour_of_day", 12)
        time_modifier = -0.05 if (hour >= 23 or hour <= 5) else 0.02 if 18 <= hour <= 22 else 0.0
        if time_modifier:
            contributions["time_of_day"] = time_modifier

        amount = math_expm1(features.get("amount_log", 0.0))
        if amount > 50_000:
            amount_modifier = 0.04   # high stakes -> more agent effort
        elif amount < 300:
            amount_modifier = -0.06  # tiny tickets not worth chasing hard
        else:
            amount_modifier = 0.0
        if amount_modifier:
            contributions["amount"] = amount_modifier

        score = min(0.97, max(0.02, reason_score + method_modifier + attempt_modifier + time_modifier + amount_modifier))
        return round(score, 4), contributions

    # ------------------------------------------------------------------
    @staticmethod
    def band_name(score: float) -> str:
        return band_of(score)[1]


def band_of(score: float) -> Tuple[float, str]:
    """Map a raw score to (score, band name)."""
    for name, low, high in BANDS:
        if low <= score < high:
            return score, name
    return score, "critical"


def math_expm1(value: float) -> float:
    import math

    return math.expm1(value) if value else 0.0


_default_scorer: Optional[RiskScorer] = None


def get_risk_scorer() -> RiskScorer:
    global _default_scorer
    if _default_scorer is None:
        from app.core.config import get_settings

        settings = get_settings()
        path = settings.risk_model_path or str(
            Path(settings.model_dir) / "risk_scorer.joblib"
        )
        _default_scorer = RiskScorer(model_path=path)
    return _default_scorer
