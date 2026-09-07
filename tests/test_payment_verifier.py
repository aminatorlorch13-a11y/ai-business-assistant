from datetime import datetime, timezone

from app.payment.event import PaymentProviderEvent
from app.payment.verifier import PaymentVerifier


class FakePaymentVerifier(PaymentVerifier):
    def verify(self, event):
        return None


def make_event():
    return PaymentProviderEvent(
        provider="test_provider",
        event_id="evt_123",
        event_type="payment.completed",
        payload={"payment_id": "pay_123"},
        received_at=datetime.now(timezone.utc),
    )


def test_payment_verifier_is_an_explicit_boundary():
    verifier = FakePaymentVerifier()

    assert isinstance(verifier, PaymentVerifier)


def test_payment_verifier_exposes_verify_operation():
    verifier = FakePaymentVerifier()

    assert callable(verifier.verify)
