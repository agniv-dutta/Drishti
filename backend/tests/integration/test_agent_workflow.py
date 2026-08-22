"""Integration tests for the API-backed agent orchestration flow."""


def test_agent_analyze_plan_execute_flow(client, sample_failed_payment):
    ingest = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
    assert ingest.status_code == 200
    payment_id = ingest.json()["payment_id"]

    analysis = client.post("/api/v1/payment/analyze", json={"payment_id": payment_id})
    assert analysis.status_code == 200
    assert analysis.json()["payment_id"] == payment_id

    plan = client.post("/api/v1/recovery/plan", json={"payment_id": payment_id})
    assert plan.status_code == 200
    assert plan.json()["plan"]["steps"]

    execution = client.post("/api/v1/recovery/execute", json={"payment_id": payment_id})
    assert execution.status_code == 200
    assert execution.json()["summary"]["plans_executed"] == 1


def test_agent_rejects_unknown_payment(client):
    response = client.post("/api/v1/recovery/plan", json={"payment_id": "missing-agent-payment"})
    assert response.status_code == 404
