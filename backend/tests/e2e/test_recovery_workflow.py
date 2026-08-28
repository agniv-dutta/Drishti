"""End-to-end recovery workflow tests: ingest -> detect -> plan -> execute -> metrics.

Runs against the full FastAPI app with mock providers and sqlite, mirroring
the production path (auth, validation, agents, DB persistence, audit trail).
"""

import uuid


def _payload(reason_code: str = "network_error", amount: float = 4200.0) -> dict:
    return {
        "order_id": f"order_e2e_{uuid.uuid4().hex[:12]}",
        "gateway_payment_id": f"pay_e2e_{uuid.uuid4().hex[:10]}",
        "customer": {
            "name": "E2E Tester",
            "email": "e2e@example.com",
            "phone": "+919876543210",
        },
        "amount": amount,
        "currency": "INR",
        "method": "upi",
        "status": "failed",
        "failure_reason_code": reason_code,
        "error_description": "Gateway timed out while contacting bank",
        "attempt_number": 1,
    }


class TestRecoveryPipeline:
    def test_happy_path_end_to_end(self, client):
        # 1. Ingest a failed payment
        ingest = client.post("/api/v1/payment/ingest", json=_payload())
        assert ingest.status_code == 200
        payment_id = ingest.json()["payment_id"]

        # 2. Analyze -> network errors are immediately retryable
        analyze = client.post("/api/v1/payment/analyze", json={"payment_id": payment_id})
        assert analyze.status_code == 200
        analysis = analyze.json()["analysis"]
        assert analysis["root_cause"] == "network_error"
        assert analysis["retryability"] == "immediate_retry"

        # 3. Detect candidates - our fresh payment must appear
        detect = client.post("/api/v1/recovery/detect", json={"lookback_hours": 24})
        assert detect.status_code == 200
        body = detect.json()
        assert body["scanned_count"] >= 1
        matched = [c for c in body["candidates"] if c["payment_id"] == payment_id]
        assert len(matched) >= 1

        # 4. Build an explicit plan
        plan = client.post("/api/v1/recovery/plan", json={"payment_id": payment_id})
        assert plan.status_code == 200
        plan_body = plan.json()
        assert plan_body["persisted"] is True
        assert plan_body["plan"]["strategy"] in {
            "smart_retry", "nudge_digital", "high_touch_voice",
            "crm_human_escalation", "write_off",
        }
        assert plan_body["plan"]["payment_id"] == payment_id

        # 5. Execute the plan
        execute = client.post(
            "/api/v1/recovery/execute", json={"payment_id": payment_id}
        )
        assert execute.status_code == 200
        result = execute.json()["results"][0]
        assert result["payment_id"] == payment_id
        assert len(result["outcomes"]) >= 1
        assert result["summary"]

        # 6. Recovery detail reflects execution state
        recovery_list = client.get(f"/api/v1/payment/{payment_id}")
        refs = recovery_list.json()["recoveries"]
        assert len(refs) >= 1

    def test_dry_run_does_not_execute(self, client):
        payment_id = client.post("/api/v1/payment/ingest", json=_payload()).json()["payment_id"]
        client.post("/api/v1/recovery/plan", json={"payment_id": payment_id})

        dry = client.post("/api/v1/recovery/execute", json={"payment_id": payment_id, "dry_run": True})
        assert dry.status_code == 200
        outcomes = dry.json()["results"][0]["outcomes"]
        assert all(o["status"] == "skipped" for o in outcomes)

        detail = client.get(f"/api/v1/payment/{payment_id}").json()
        statuses = [r["status"] for r in detail["recoveries"]]
        assert "succeeded" not in statuses  # dry run leaves it open


class TestAuditAndMetrics:
    def test_audit_trail_records_pipeline_events(self, client):
        payment_id = client.post("/api/v1/payment/ingest", json=_payload()).json()["payment_id"]
        client.post("/api/v1/payment/analyze", json={"payment_id": payment_id})

        trail = client.get("/api/v1/audit/trail", params={"resource_id": payment_id})
        assert trail.status_code == 200
        events = trail.json()["events"]
        types = {e["event_type"] for e in events}
        assert "payment_ingested" in types
        assert "payment_analyzed" in types

    def test_exceptions_endpoint_lists_failures(self, client):
        exceptions = client.get("/api/v1/audit/exceptions")
        assert exceptions.status_code == 200
        assert {"total", "exceptions"} <= set(exceptions.json().keys())

    def test_metrics_reflect_executions(self, client):
        payment_id = client.post("/api/v1/payment/ingest", json=_payload()).json()["payment_id"]
        client.post("/api/v1/recovery/plan", json={"payment_id": payment_id})
        client.post("/api/v1/recovery/execute", json={"payment_id": payment_id})

        rate = client.get("/api/v1/metrics/recovery-rate", params={"period_days": 30})
        assert rate.status_code == 200
        rate_body = rate.json()
        assert rate_body["total_attempts"] >= 1

        cost = client.get("/api/v1/metrics/cost-analysis", params={"period_days": 30})
        assert cost.status_code == 200
        assert cost.json()["period_days"] == 30

    def test_health_reports_components(self, client):
        health = client.get("/health").json()
        assert health["components"]["database"] == "up"
        assert health["components"]["database_mode"] in {"sqlite", "sqlite-fallback", "postgresql"}
