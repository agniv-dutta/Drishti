from datetime import datetime, timezone

from app.ml.contact_time_predictor import ContactTimePredictor


def test_professional_profile_prefers_evening_and_exceeds_contact_threshold():
    prediction = ContactTimePredictor().predict({"customer_segment": "working professional"})

    assert prediction.hour == 21
    assert prediction.success_probability == 0.72
    assert prediction.success_probability > ContactTimePredictor.HIGH_SUCCESS_PROBABILITY


def test_housewife_profile_prefers_midday():
    prediction = ContactTimePredictor().predict({"customer_segment": "housewife"})

    assert prediction.hour in {11, 12}
    assert prediction.success_probability == 0.68


def test_historical_labels_override_profile_fallback():
    predictor = ContactTimePredictor().train([
        {"customer_segment": "professional", "hour_utc": 9, "recovery_success": "full"},
        {"customer_segment": "professional", "hour_utc": 9, "recovery_success": "full"},
        {"customer_segment": "professional", "hour_utc": 9, "recovery_success": "full"},
    ])

    prediction = predictor.predict({"customer_segment": "professional"})

    assert prediction.hour == 9
    assert prediction.source == "historical"
    assert prediction.success_probability == 0.8


def test_scheduled_contact_uses_customer_timezone_and_immediate_override():
    predictor = ContactTimePredictor()
    prediction = predictor.predict({
        "customer_segment": "professional",
        "location_timezone": "Asia/Kolkata",
    })
    now = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)

    scheduled = predictor.scheduled_at(prediction, now)
    immediate = predictor.scheduled_at(prediction, now, immediate=True)

    assert scheduled.hour == 15
    assert scheduled.tzinfo == timezone.utc
    assert immediate == now