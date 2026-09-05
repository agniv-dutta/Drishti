def test_subscription_progressive_recovery_and_churn_risk(client):
    created = client.post(
        "/api/v1/recovery/subscription/payments",
        json={
            "merchant_id": "merchant-sub",
            "customer_id": "customer-sub-1",
            "customer_name": "Riya Sharma",
            "customer_email": "riya@example.com",
            "subscription_id": "sub-001",
            "subscription_name": "Growth Plan",
            "billing_cycle": 4,
            "amount": 2499,
            "failure_reason": "expired_card",
            "months_active": 2,
            "support_complaints": 1,
            "lifetime_value": 7497,
        },
    )
    assert created.status_code == 200, created.text
    payment_id = created.json()["data"]["id"]

    expected = ["immediate_retry", "delayed_retry", "card_update_prompt", "suspend_warning"]
    for strategy in expected:
        response = client.post(
            "/api/v1/recovery/subscription/handle-failure",
            params={"subscription_payment_id": payment_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["strategy"] == strategy
    risk = client.get(
        "/api/v1/recovery/subscription/churn-risk",
        params={"customer_id": "customer-sub-1"},
    )
    assert risk.status_code == 200, risk.text
    assert 0 < risk.json()["data"]["churn_risk"] <= 1
    assert risk.json()["data"]["recommendation"]
