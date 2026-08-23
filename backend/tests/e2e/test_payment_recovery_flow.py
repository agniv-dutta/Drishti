"""End-to-end payment recovery assertions."""


def test_failed_payment_recovers_and_is_audited(client, sample_failed_payment, auto_confidence):
    ingest = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
    assert ingest.status_code == 200
    payment_id = ingest.json()["payment_id"]

    analysis = client.post("/api/v1/payment/analyze", json={"payment_id": payment_id})
    assert analysis.status_code == 200

    plan = client.post("/api/v1/recovery/plan", json={"payment_id": payment_id})
    assert plan.status_code == 200

    execution = client.post("/api/v1/recovery/execute", json={"payment_id": payment_id})
    assert execution.status_code == 200
    result = execution.json()["results"][0]
    assert result["recovered_amount_paise"] > 0

    audit = client.get("/api/v1/audit/trail", params={"resource_id": payment_id})
    assert audit.status_code == 200
    events = {event["event_type"] for event in audit.json()["events"]}
    assert {"payment_ingested", "payment_analyzed"} <= events
