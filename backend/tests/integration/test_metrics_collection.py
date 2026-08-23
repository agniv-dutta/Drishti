"""Metrics collector and Prometheus endpoint tests."""

from app.metrics.collector import MetricsCollector


def test_model_drift_is_mean_absolute_error():
    assert MetricsCollector.model_drift_score([0.2, 0.8], [0.1, 0.5]) == 0.2
    assert MetricsCollector.model_drift_score([], []) == 0.0


def test_metrics_summary_and_prometheus_export(client, sample_failed_payment, auto_confidence):
    ingest = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
    payment_id = ingest.json()["payment_id"]
    assert client.post("/api/v1/recovery/plan", json={"payment_id": payment_id}).status_code == 200
    assert client.post("/api/v1/recovery/execute", json={"payment_id": payment_id}).status_code == 200

    summary = client.get("/api/v1/metrics/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_payments_attempted"] == 1
    assert body["payments_recovered"] == 1
    assert body["recovery_rate"] == 1.0
    assert body["average_recovery_percent"] > 0
    assert body["cost_per_recovery_inr"] >= 0
    assert 0 <= body["false_positive_rate"] <= 1

    prometheus = client.get("/api/v1/metrics/prometheus")
    assert prometheus.status_code == 200
    assert "drishti_recovery_rate" in prometheus.text
    assert "drishti_model_drift_score" in prometheus.text


