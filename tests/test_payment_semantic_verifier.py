from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.payment.event import PaymentProviderEvent
from app.payment.fact_extractor import PaymentFactExtractor
from app.payment.facts import PaymentFacts
from app.payment.request import PaymentVerificationRequest
from app.payment.semantic_verifier import SemanticPaymentVerifier
from app.payment.verification import (
    PaymentVerificationStatus,
)


class FakeExtractor(PaymentFactExtractor):
    def __init__(self, facts):
        self.facts = facts
        self.calls = 0

    def extract(self, event):
        self.calls += 1
        return self.facts


def make_event():
    return PaymentProviderEvent(
        provider="test-provider",
        event_id="evt-001",
        event_type="payment.completed",
        payload={"payment": {"status": "paid"}},
        received_at=datetime(
            2026,
            9,
            1,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_request():
    return PaymentVerificationRequest(
        business_id="business-001",
        expected_amount=Decimal("300.00"),
        expected_currency="ZAR",
        requested_at=datetime(
            2026,
            9,
            1,
            11,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_facts():
    return PaymentFacts(
        business_id="business-001",
        amount=Decimal("300.00"),
        currency="ZAR",
        payment_status="paid",
        paid_at=datetime(
            2026,
            9,
            1,
            11,
            30,
            tzinfo=timezone.utc,
        ),
    )


def test_matching_payment_becomes_verified_purchase():
    extractor = FakeExtractor(make_facts())
    verifier = SemanticPaymentVerifier(extractor)

    result = verifier.verify(
        make_event(),
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.VERIFIED
    assert isinstance(result.purchase, VerifiedPurchase)
    assert result.purchase.business_id == "business-001"
    assert result.purchase.amount == Decimal("300.00")
    assert result.purchase.currency == "ZAR"
    assert result.purchase.provider == "test-provider"
    assert result.purchase.provider_event_id == "evt-001"
    assert extractor.calls == 1


def test_business_mismatch_is_rejected():
    facts = make_facts()
    facts = PaymentFacts(
        business_id="attacker-business",
        amount=facts.amount,
        currency=facts.currency,
        payment_status=facts.payment_status,
        paid_at=facts.paid_at,
    )

    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    result = verifier.verify(
        make_event(),
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.purchase is None
    assert result.reason == "business identity mismatch"


def test_amount_mismatch_is_rejected():
    facts = PaymentFacts(
        business_id="business-001",
        amount=Decimal("1.00"),
        currency="ZAR",
        payment_status="paid",
        paid_at=datetime(
            2026,
            9,
            1,
            11,
            30,
            tzinfo=timezone.utc,
        ),
    )

    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    result = verifier.verify(
        make_event(),
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.reason == "payment amount mismatch"


def test_currency_mismatch_is_rejected():
    facts = PaymentFacts(
        business_id="business-001",
        amount=Decimal("300.00"),
        currency="USD",
        payment_status="paid",
        paid_at=datetime(
            2026,
            9,
            1,
            11,
            30,
            tzinfo=timezone.utc,
        ),
    )

    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    result = verifier.verify(
        make_event(),
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.reason == "payment currency mismatch"


@pytest.mark.parametrize(
    "status",
    [
        "pending",
        "processing",
        "failed",
        "cancelled",
        "refunded",
    ],
)
def test_non_paid_status_is_rejected(status):
    facts = PaymentFacts(
        business_id="business-001",
        amount=Decimal("300.00"),
        currency="ZAR",
        payment_status=status,
        paid_at=datetime(
            2026,
            9,
            1,
            11,
            30,
            tzinfo=timezone.utc,
        ),
    )

    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    result = verifier.verify(
        make_event(),
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.reason == "payment is not confirmed as paid"


def test_payment_after_event_receipt_is_rejected():
    facts = PaymentFacts(
        business_id="business-001",
        amount=Decimal("300.00"),
        currency="ZAR",
        payment_status="paid",
        paid_at=datetime(
            2026,
            9,
            1,
            12,
            1,
            tzinfo=timezone.utc,
        ),
    )

    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    result = verifier.verify(
        make_event(),
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.reason == (
        "payment timestamp occurs after event receipt"
    )


def test_invalid_event_type_is_rejected_by_boundary():
    verifier = SemanticPaymentVerifier(
        FakeExtractor(make_facts())
    )

    with pytest.raises(TypeError):
        verifier.verify(
            object(),
            make_request(),
        )


def test_invalid_request_type_is_rejected_by_boundary():
    verifier = SemanticPaymentVerifier(
        FakeExtractor(make_facts())
    )

    with pytest.raises(TypeError):
        verifier.verify(
            make_event(),
            object(),
        )


def test_invalid_extractor_result_is_rejected():
    class InvalidExtractor(PaymentFactExtractor):
        def extract(self, event):
            return object()

    verifier = SemanticPaymentVerifier(
        InvalidExtractor()
    )

    with pytest.raises(TypeError):
        verifier.verify(
            make_event(),
            make_request(),
        )


def test_rejected_result_never_contains_purchase():
    facts = PaymentFacts(
        business_id="wrong-business",
        amount=Decimal("300.00"),
        currency="ZAR",
        payment_status="paid",
        paid_at=datetime(
            2026,
            9,
            1,
            11,
            30,
            tzinfo=timezone.utc,
        ),
    )

    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    result = verifier.verify(
        make_event(),
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.purchase is None
