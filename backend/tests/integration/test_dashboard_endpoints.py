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


def test_dashboard_journey_includes_chargeback_risk_for_sms_recovery(client, sample_failed_payment):
    payload = dict(sample_failed_payment)
    payload["metadata"] = dict(sample_failed_payment.get("metadata", {}))
    payload["metadata"].update(
        {
            "first_purchase": "true",
            "previous_chargebacks": "2",
            "product_category": "subscriptions",
            "card_type": "credit",
        }
    )

    ingest = client.post("/api/v1/payment/ingest", json=payload)
    assert ingest.status_code == 200, ingest.text
    payment_id = ingest.json()["payment_id"]

    plan = client.post(
        "/api/v1/recovery/plan",
        json={"payment_id": payment_id, "override_strategy": "nudge_digital"},
    )
    assert plan.status_code == 200, plan.text

    execution = client.post("/api/v1/recovery/execute", json={"payment_id": payment_id})
    assert execution.status_code == 200, execution.text
    execution_body = execution.json()["results"][0]
    chargeback_risk = execution_body["chargeback_risk"]
    assert chargeback_risk["risk_score_pct"] > 40
    assert chargeback_risk["manual_review_required"] is True
    assert "invoice_pdf" in chargeback_risk["evidence_to_store"]

    overview = client.get("/api/v1/dashboard/overview")
    assert overview.status_code == 200, overview.text
    overview_body = overview.json()
    overview_risks = [
        item["chargeback_risk"]["risk_score_pct"]
        for item in overview_body["active_recoveries"]
        if item.get("chargeback_risk")
    ]
    assert any(score > 40 for score in overview_risks)

    journey = client.get(f"/api/v1/dashboard/journey/{payment_id}")
    assert journey.status_code == 200, journey.text
    journey_body = journey.json()
    assert journey_body["chargeback_risk"]["risk_score_pct"] > 40
    assert journey_body["chargeback_risk"]["manual_review_required"] is True
