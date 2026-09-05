from datetime import timedelta

from app.models.payment import utcnow


def test_b2b_overdue_detection_reminder_and_dso(client):
    now = utcnow()
    created = client.post(
        "/api/v1/recovery/b2b/invoices",
        json={
            "merchant_id": "merchant-b2b",
            "customer_id": "acme-001",
            "customer_name": "Acme Industries",
            "customer_contact_name": "Priya Mehta",
            "customer_email": "ap@acme.example",
            "invoice_number": "INV-1001",
            "amount": 120000,
            "issue_date": (now - timedelta(days=45)).isoformat(),
            "due_date": (now - timedelta(days=15)).isoformat(),
            "payment_terms": "Net 30",
            "status": "overdue",
        },
    )
    assert created.status_code == 200, created.text
    invoice_id = created.json()["data"]["id"]

    detected = client.post(
        "/api/v1/recovery/b2b/detect-overdue",
        params={"merchant_id": "merchant-b2b"},
    )
    assert detected.status_code == 200, detected.text
    assert detected.json()["data"]["overdue_invoices"][0]["invoice_id"] == invoice_id

    reminder = client.post(
        "/api/v1/recovery/b2b/send-reminder",
        params={"invoice_id": invoice_id},
    )
    assert reminder.status_code == 200, reminder.text
    assert reminder.json()["data"]["status"] == "reminder_sent"

    detail = client.get(f"/api/v1/recovery/b2b/invoices/{invoice_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["reminder_count"] == 1
    assert detail.json()["data"]["reminders"][0]["template"] == "soft_reminder"

    dso = client.get(
        "/api/v1/recovery/b2b/dso-tracker",
        params={"merchant_id": "merchant-b2b"},
    )
    assert dso.status_code == 200, dso.text
    assert dso.json()["data"]["overdue_invoices"] == 1
    assert dso.json()["data"]["dso"] > 0
