"""Unit tests for strategy decision logic and drift detection."""

import pytest

from app.ml.drift_detector import DriftDetector, population_stability_index
from app.models.payment import Retryability
from app.ml.recovery_classifier import RecoveryClassifier


class TestClassifier:
    def setup_method(self):
        self.classifier = RecoveryClassifier()

    def test_immediate_retry_maps_to_smart_retry(self):
        strategy = self.classifier.choose_strategy(
            Retryability.IMMEDIATE_RETRY, risk_score=0.5,
            amount_inr=1000, high_value_threshold_inr=25000,
        )
        assert strategy.value == "smart_retry"

    def test_customer_action_low_value_maps_to_nudge(self):
        strategy = self.classifier.choose_strategy(
            Retryability.CUSTOMER_ACTION_REQUIRED, risk_score=0.40,
            amount_inr=5000, high_value_threshold_inr=25000,
        )
        assert strategy.value == "nudge_digital"

    def test_customer_action_high_value_maps_to_voice(self):
        strategy = self.classifier.choose_strategy(
            Retryability.CUSTOMER_ACTION_REQUIRED, risk_score=0.70,
            amount_inr=50000, high_value_threshold_inr=25000,
        )
        assert strategy.value == "high_touch_voice"

    def test_not_retryable_maps_to_write_off(self):
        strategy = self.classifier.choose_strategy(
            Retryability.NOT_RETRYABLE, risk_score=0.2,
            amount_inr=5000, high_value_threshold_inr=25000,
        )
        assert strategy.value == "write_off"

    def test_channel_ranking_descends_by_probability(self):
        ranked = self.classifier.rank_channels(Retryability.IMMEDIATE_RETRY)
        probs = [p for _, p in ranked]
        assert probs == sorted(probs, reverse=True)


class TestPSI:
    def test_identical_distributions_stable(self):
        values = [float(i % 10) for i in range(1000)]
        psi = population_stability_index(values, values)
        assert psi < 0.05

    def test_shifted_distribution_flags_drift(self):
        reference = [float(i % 10) for i in range(1000)]
        shifted = [min(9.0, float(i % 10) + 6.0) for i in range(1000)]
        psi = population_stability_index(reference, shifted)
        assert psi > 0.25

    def test_detector_end_to_end(self):
        detector = DriftDetector(threshold=0.2)
        reference = {
            "amount_log": [float((i * 7) % 12) for i in range(200)],
            "hour_of_day": [float(i % 24) for i in range(200)],
        }
        detector.update_reference(reference)
        drifted_batch = {
            "amount_log": [11.5] * 200,
            "hour_of_day": [float(i % 24) for i in range(200)],
        }
        report = detector.check(drifted_batch)
        assert isinstance(report["drifted"], bool)
