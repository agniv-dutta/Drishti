"""Integration tests for the dashboard aggregation endpoints."""

from __future__ import annotations


def test_dashboard_overview_and_journey(client, sample_failed_payment):
    ingest = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
    assert ingest.status_code == 200, ingest.text
    payment_id = ingest.json()["payment_id"]

    assert client.post("/api/v1/recovery/plan", json={"payment_id": payment_id}).status_code == 200
    assert client.post("/api/v1/recovery/execute", json={"payment_id": payment_id}).status_code == 200

    overview = client.get("/api/v1/dashboard/overview")
    assert overview.status_code == 200, overview.text
    overview_body = overview.json()
    assert overview_body["selected_payment_id"] == payment_id
    assert overview_body["total_payments_processed"] >= 1
    assert overview_body["active_recoveries"]
    assert overview_body["activity_feed"]

    journey = client.get(f"/api/v1/dashboard/journey/{payment_id}")
    assert journey.status_code == 200, journey.text
    journey_body = journey.json()
    assert journey_body["payment_id"] == payment_id
    assert journey_body["nodes"]
    assert journey_body["nodes"][0]["id"] == "created"
