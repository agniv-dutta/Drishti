"""Recovery channel/strategy classification.

Rule-based decision matrix out of the box; upgrades to a trained sklearn
classifier when ``CLASSIFIER_MODEL_PATH`` is set (predict_proba over
RecoveryStrategy classes).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.models.payment import PaymentTransaction, Retryability
from app.models.recovery import RecoveryChannel, RecoveryStrategy

logger = logging.getLogger(__name__)

# P(conversion | channel) per retryability class - tuned heuristics.
_CHANNEL_PROBS: Dict[Retryability, List[Tuple[RecoveryChannel, float]]] = {
    Retryability.IMMEDIATE_RETRY: [
        (RecoveryChannel.GATEWAY_RETRY, 0.82),
        (RecoveryChannel.SMS, 0.50),
        (RecoveryChannel.EMAIL, 0.45),
    ],
    Retryability.DELAYED_RETRY: [
        (RecoveryChannel.GATEWAY_RETRY, 0.64),
        (RecoveryChannel.SMS, 0.58),
        (RecoveryChannel.EMAIL, 0.52),
        (RecoveryChannel.VOICE_IVR, 0.40),
    ],
    Retryability.CUSTOMER_ACTION_REQUIRED: [
        (RecoveryChannel.SMS, 0.52),
        (RecoveryChannel.EMAIL, 0.48),
        (RecoveryChannel.VOICE_IVR, 0.44),
        (RecoveryChannel.CRM_ESCALATION, 0.30),
    ],
    Retryability.NOT_RETRYABLE: [
        (RecoveryChannel.CRM_ESCALATION, 0.18),
    ],
}


class RecoveryClassifier:
    """Ranks channels and picks a strategy for a failed payment."""

    def __init__(self, model_path: Optional[str] = None):
        self._model = None
        if model_path and Path(model_path).exists():
            try:
                import joblib

                self._model = joblib.load(model_path)
                logger.info("recovery_classifier.model_loaded", path=model_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("recovery_classifier.model_load_failed", error=str(exc))

    @property
    def using_ml_model(self) -> bool:
        return self._model is not None

    def rank_channels(
        self,
        retryability: Retryability,
        features: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[RecoveryChannel, float]]:
        """Channels sorted by expected conversion probability."""
        base = dict(_CHANNEL_PROBS.get(retryability, _CHANNEL_PROBS[Retryability.CUSTOMER_ACTION_REQUIRED]))

        # Small feature-driven adjustments.
        if features:
            if features.get("method_upi") == 1.0:
                base[RecoveryChannel.SMS] = min(0.95, base.get(RecoveryChannel.SMS, 0.5) + 0.06)
            if features.get("amount_log", 0) > 11.5:  # > ~Rs 1L
                base[RecoveryChannel.VOICE_IVR] = min(0.95, base.get(RecoveryChannel.VOICE_IVR, 0.4) + 0.08)
                base.setdefault(RecoveryChannel.CRM_ESCALATION, 0.30)

        return sorted(base.items(), key=lambda item: item[1], reverse=True)

    def choose_strategy(
        self,
        retryability: Retryability,
        risk_score: float,
        amount_inr: float,
        high_value_threshold_inr: float,
    ) -> RecoveryStrategy:
        """Decision table mapping analysis -> strategy."""
        if retryability == Retryability.NOT_RETRYABLE:
            return RecoveryStrategy.WRITE_OFF
        if retryability == Retryability.IMMEDIATE_RETRY:
            return RecoveryStrategy.SMART_RETRY
        if retryability == Retryability.DELAYED_RETRY:
            return RecoveryStrategy.NUDGE_DIGITAL
        # CUSTOMER_ACTION_REQUIRED
        if amount_inr >= high_value_threshold_inr or risk_score >= 0.65:
            return RecoveryStrategy.HIGH_TOUCH_VOICE
        return RecoveryStrategy.NUDGE_DIGITAL

    def predict_proba(
        self,
        txn: PaymentTransaction,
        features: Dict[str, float],
    ) -> List[Tuple[str, float]]:
        """Optional ML override returning [(strategy_value, prob)] sorted."""
        if self._model is None:
            return []
        try:
            from app.ml.data_preprocessor import FEATURE_NAMES

            row = [features[name] for name in FEATURE_NAMES]
            probs = self._model.predict_proba([row])[0]
            classes = [str(cls) for cls in getattr(self._model, "classes_", range(len(probs)))]
            ranked = sorted(zip(classes, map(float, probs)), key=lambda p: p[1], reverse=True)
            return ranked
        except Exception as exc:  # noqa: BLE001
            logger.warning("recovery_classifier.ml_predict_failed", error=str(exc))
            return []


_default_classifier: Optional[RecoveryClassifier] = None


def get_recovery_classifier() -> RecoveryClassifier:
    global _default_classifier
    if _default_classifier is None:
        from app.core.config import get_settings

        settings = get_settings()
        path = settings.classifier_model_path or str(
            Path(settings.model_dir) / "recovery_classifier.joblib"
        )
        _default_classifier = RecoveryClassifier(model_path=path)
    return _default_classifier
