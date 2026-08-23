"""Unit tests for the chargeback prevention scorer."""

from __future__ import annotations

from app.ml.chargeback_risk import predict_chargeback_risk
from app.models.payment import CustomerInfo, PaymentMethod, PaymentStatus, PaymentTransaction
from app.models.recovery import RecoveryChannel, RecoveryStrategy, StepOutcome, StepStatus


def _txn(
    *,
    amount_paise: int = 125000,
    attempt_number: int = 2,
    method: PaymentMethod = PaymentMethod.CARD,
    **meta,
):
    return PaymentTransaction(
        payment_id="pay_test_123",
        order_id="order_test_123",
        customer=CustomerInfo(name="Asha Kumar", email="asha@example.com", phone="+919999999999"),
        amount_paise=amount_paise,
        currency="INR",
        method=method,
        status=PaymentStatus.CAPTURED,
        attempt_number=attempt_number,
        meta=meta,
    )


def _sms_success():
    return [
        StepOutcome(
            sequence=1,
            channel=RecoveryChannel.SMS,
            status=StepStatus.SUCCEEDED,
            detail="sms delivered",
        )
    ]


def _gateway_success():
    return [
        StepOutcome(
            sequence=1,
            channel=RecoveryChannel.GATEWAY_RETRY,
            status=StepStatus.SUCCEEDED,
            detail="gateway retry succeeded",
        )
    ]


class TestChargebackRisk:
    def test_high_risk_sms_recovery_flags_manual_review(self):
        assessment = predict_chargeback_risk(
            _txn(
                first_purchase="true",
                previous_chargebacks="2",
                product_category="subscriptions",
                card_type="credit",
                previous_successful_payments="0",
            ),
            RecoveryStrategy.NUDGE_DIGITAL,
            _sms_success(),
        )

        assert assessment is not None
        assert assessment.risk_score_pct > 40
        assert assessment.manual_review_required is True
        assert "sms_delivery_proof" in assessment.evidence_to_store
        assert "invoice_pdf" in assessment.evidence_to_store
        assert any("manual review" in action.lower() for action in assessment.recommended_actions)

    def test_low_risk_sms_recovery_stays_under_threshold(self):
        assessment = predict_chargeback_risk(
            _txn(
                amount_paise=5000,
                attempt_number=1,
                method=PaymentMethod.WALLET,
                first_purchase="false",
                previous_chargebacks="0",
                product_category="physical_goods",
                previous_successful_payments="8",
            ),
            RecoveryStrategy.NUDGE_DIGITAL,
            _sms_success(),
        )

        assert assessment is not None
        assert assessment.risk_score_pct <= 40
        assert assessment.manual_review_required is False
        assert assessment.recommended_actions[0].startswith("Keep the receipt")

    def test_gateway_retry_does_not_trigger_chargeback_assessment(self):
        assessment = predict_chargeback_risk(
            _txn(
                first_purchase="true",
                previous_chargebacks="1",
                product_category="digital_goods",
                card_type="credit",
            ),
            RecoveryStrategy.SMART_RETRY,
            _gateway_success(),
        )

        assert assessment is None
