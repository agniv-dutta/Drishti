"""Integration tests for the /payment endpoints (mock providers, sqlite)."""

import uuid


class TestAuth:
    def test_missing_api_key_rejected(self, client):
        response = client.post(
            "/api/v1/payment/ingest", json={"order_id": "x"}, headers={"X-API-Key": ""}
        )
        assert response.status_code == 401

    def test_wrong_api_key_rejected(self, client):
        response = client.get("/api/v1/audit/trail", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401


class TestIngest:
    def test_ingest_success(self, client, sample_failed_payment):
        response = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
        assert response.status_code == 200
        body = response.json()
        assert body["payment_id"]
        assert body["duplicate"] is False
        assert body["status"] == "failed"

    def test_duplicate_ingest_is_idempotent(self, client, sample_failed_payment):
        first = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
        second = client.post("/api/v1/payment/ingest", json=sample_failed_payment)
        assert first.json()["payment_id"] == second.json()["payment_id"]
        assert second.json()["duplicate"] is True

    def test_invalid_phone_returns_422(self, client):
        payload = {
            "order_id": f"order_bad_{uuid.uuid4().hex[:8]}",
            "customer": {"name": "Bad Phone", "email": "bad@example.com", "phone": "12345"},
            "amount": 500.0,
            "method": "card",
        }
        response = client.post("/api/v1/payment/ingest", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_negative_amount_rejected(self, client):
        payload = {
            "order_id": f"order_neg_{uuid.uuid4().hex[:8]}",
            "customer": {"name": "Neg", "email": "n@example.com", "phone": "+919876543210"},
            "amount": -10,
            "method": "upi",
        }
        assert client.post("/api/v1/payment/ingest", json=payload).status_code == 422


class TestAnalyzeAndDetail:
    def test_analyze_returns_analysis(self, client, ingested_payment):
        response = client.post(
            "/api/v1/payment/analyze", json={"payment_id": ingested_payment["payment_id"]}
        )
        assert response.status_code == 200
        analysis = response.json()["analysis"]
        valid_reasons = {
            "insufficient_funds", "authentication_timeout", "bank_decline",
            "invalid_card_details", "card_expired", "network_error",
            "risk_blocked", "customer_dropoff", "unknown",
        }
        assert analysis["root_cause"] in valid_reasons
        assert 0 <= analysis["risk_score"] <= 1
        assert analysis["retryability"] in {
            "immediate_retry", "delayed_retry", "customer_action_required", "not_retryable"
        }

    def test_analyze_unknown_payment_404(self, client):
        response = client.post("/api/v1/payment/analyze", json={"payment_id": "missing"})
        assert response.status_code == 404

    def test_detail_masks_pii(self, client, ingested_payment):
        response = client.get(f"/api/v1/payment/{ingested_payment['payment_id']}")
        assert response.status_code == 200
        txn = response.json()["transaction"]
        raw_email = ingested_payment["customer"]["email"]
        assert txn["customer_email"] != raw_email
        assert "\u2022" in txn["customer_email"]
