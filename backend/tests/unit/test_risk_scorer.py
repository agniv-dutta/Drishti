"""Unit tests for the heuristic risk scorer and band mapping."""

from app.ml.risk_scorer import RiskScorer, band_of


def _features(reason: str, method: str = "card", attempts: int = 1, hour: int = 14) -> dict:
    features = {name: 0.0 for name in [
        "amount_log", "attempt_number", "hour_of_day", "day_of_week", "is_weekend",
        "method_card", "method_netbanking", "method_upi", "method_wallet", "method_emi",
        f"reason_{reason}",
    ]}
    features["attempt_number"] = attempts
    features["hour_of_day"] = hour
    features[f"method_{method}"] = 1.0
    features[f"reason_{reason}"] = 1.0
    return features


class TestScorer:
    def test_score_within_bounds_and_band(self):
        scorer = RiskScorer()
        score, band, contributions = scorer.score(_features("insufficient_funds"))
        assert 0.0 <= score <= 1.0
        assert band in {"low", "medium", "high", "critical"}
        assert isinstance(contributions, dict)

    def test_easy_reason_scores_higher_than_hard_reason(self):
        scorer = RiskScorer()
        easy, _, _ = scorer.score(_features("network_error"))
        hard, _, _ = scorer.score(_features("risk_blocked"))
        assert easy > hard

    def test_attempt_fatigue_penalises(self):
        scorer = RiskScorer()
        fresh, _, _ = scorer.score(_features("insufficient_funds", attempts=1))
        tired, _, _ = scorer.score(_features("insufficient_funds", attempts=4))
        assert fresh > tired

    def test_band_boundaries(self):
        assert band_of(0.10)[1] == "low"
        assert band_of(0.50)[1] == "medium"
        assert band_of(0.70)[1] == "high"
        assert band_of(0.90)[1] == "critical"
