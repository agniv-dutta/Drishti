"""Database CRUD and domain rehydration tests."""

from app.database.models import PaymentRecord
from app.database.session import get_session_factory, init_db
from app.models.payment import CustomerInfo, PaymentMethod, PaymentStatus, PaymentTransaction
from app.utils.encryption import encrypt_dict


def _record():
    transaction = PaymentTransaction(
        payment_id="db-payment-1",
        order_id="db-order-1",
        customer=CustomerInfo(name="DB User", email="db@example.com", phone="+919876543210"),
        amount_paise=12500,
        method=PaymentMethod.UPI,
        status=PaymentStatus.FAILED,
        failure_reason="bank_decline",
    )
    return PaymentRecord.from_domain(
        transaction,
        encrypt_dict({"email": transaction.customer.email, "phone": transaction.customer.phone}),
    )


def test_payment_record_create_read_update_delete():
    init_db()
    session = get_session_factory()()
    try:
        record = _record()
        session.add(record)
        session.commit()

        loaded = session.get(PaymentRecord, record.id)
        assert loaded is not None
        assert loaded.to_domain().customer.email == "db@example.com"
        assert loaded.public_view()["customer_email"] != "db@example.com"

        loaded.status = "captured"
        session.commit()
        assert session.get(PaymentRecord, record.id).status == "captured"

        session.delete(loaded)
        session.commit()
        assert session.get(PaymentRecord, record.id) is None
    finally:
        session.close()
