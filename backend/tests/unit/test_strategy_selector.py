"""Unit tests for recovery strategy selection and confidence handling."""

from app.ml.data_preprocessor import build_strategy_features
from app.ml.recovery_classifier import RecoveryClassifier
from app.ml.strategy_model import strategy_feature_vector
from app.models.payment import Retryability


class FakeStrategyModel:
    classes_ = [0, 1, 2, 3, 4]

    def __init__(self, probabilities):
        self.probabilities = probabilities

    def predict_proba(self, rows):
        assert len(rows) == 1
        return [self.probabilities]


def _features():
    return build_strategy_features(
        "bank_decline", "retained", 1, 2, "sms"
    )


def test_strategy_features_have_stable_encoded_shape():
    vector = strategy_feature_vector(_features())
    assert len(vector) == 18
    assert sum(vector[:9]) == 1
    assert sum(vector[9:12]) == 1
    assert sum(vector[14:]) == 1


def test_high_confidence_prediction_returns_strategy_and_alternates():
    classifier = RecoveryClassifier()
    classifier._model = FakeStrategyModel([0.03, 0.82, 0.08, 0.04, 0.03])

    result = classifier.predict_strategy(_features())

    assert result["recommended_strategy"] == "sms"
    assert result["confidence"] == 0.82
    assert len(result["alternate_strategies"]) == 2
    assert result["stop_after_days"] == 7


def test_low_confidence_prediction_escalates():
    classifier = RecoveryClassifier()
    classifier._model = FakeStrategyModel([0.40, 0.25, 0.15, 0.10, 0.10])

    assert classifier.predict_strategy(_features())["recommended_strategy"] == "escalate"


def test_missing_model_escalates():
    result = RecoveryClassifier().predict_strategy(_features())
    assert result["recommended_strategy"] == "escalate"
    assert result["confidence"] == 0.0


def test_invalid_strategy_feature_values_rejected():
    try:
        build_strategy_features("bank_decline", "new", -1, 0, "sms")
    except ValueError as exc:
        assert "failure_count" in str(exc)
    else:
        raise AssertionError("negative failure count was accepted")


def test_existing_rule_strategy_selector_remains_available():
    strategy = RecoveryClassifier().choose_strategy(
        Retryability.IMMEDIATE_RETRY, 0.1, 1000, 25000
    )
    assert strategy.value == "smart_retry"
