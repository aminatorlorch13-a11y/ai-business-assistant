from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.payment.event import PaymentProviderEvent
from app.payment.fact_extractor import PaymentFactExtractor
from app.payment.facts import PaymentFacts
from app.payment.request import PaymentVerificationRequest
from app.payment.semantic_verifier import SemanticPaymentVerifier
from app.payment.verification import PaymentVerificationStatus


class FakeExtractor(PaymentFactExtractor):
    def __init__(self, facts):
        self.facts = facts
        self.calls = 0

    def extract(self, event):
        self.calls += 1
        return self.facts


class RaisingExtractor(PaymentFactExtractor):
    def extract(self, event):
        raise RuntimeError("provider parsing failure")


def make_event():
    return PaymentProviderEvent(
        provider="test-provider",
        event_id="evt-001",
        event_type="payment.completed",
        payload={
            "payment": {
                "status": "paid",
                "amount": "300.00",
            }
        },
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


def make_facts(**overrides):
    values = {
        "business_id": "business-001",
        "amount": Decimal("300.00"),
        "currency": "ZAR",
        "payment_status": "paid",
        "paid_at": datetime(
            2026,
            9,
            1,
            11,
            30,
            tzinfo=timezone.utc,
        ),
    }

    values.update(overrides)

    return PaymentFacts(**values)


def verify(facts, request=None):
    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    return verifier.verify(
        make_event(),
        request or make_request(),
    )


def test_event_payload_is_deeply_immutable():
    original = {
        "payment": {
            "amount": "300.00",
            "metadata": {
                "business_id": "business-001",
            },
        }
    }

    event = PaymentProviderEvent(
        provider="test-provider",
        event_id="evt-001",
        event_type="payment.completed",
        payload=original,
        received_at=datetime.now(timezone.utc),
    )

    original["payment"]["amount"] = "999999.00"
    original["payment"]["metadata"]["business_id"] = "attacker"

    assert event.payload["payment"]["amount"] == "300.00"
    assert (
        event.payload["payment"]["metadata"]["business_id"]
        == "business-001"
    )


def test_event_payload_nested_mapping_cannot_be_modified():
    event = make_event()

    with pytest.raises(TypeError):
        event.payload["payment"]["status"] = "paid"


def test_event_payload_nested_list_is_immutable():
    event = PaymentProviderEvent(
        provider="test-provider",
        event_id="evt-list",
        event_type="payment.completed",
        payload={
            "items": [
                {"amount": "300.00"},
            ]
        },
        received_at=datetime.now(timezone.utc),
    )

    assert isinstance(event.payload["items"], tuple)

    with pytest.raises(TypeError):
        event.payload["items"][0]["amount"] = "999.00"


def test_business_substitution_is_rejected():
    result = verify(
        make_facts(
            business_id="attacker-business"
        )
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.purchase is None


def test_expected_business_id_cannot_be_bypassed_by_event_payload():
    facts = make_facts(
        business_id="business-001"
    )

    event = PaymentProviderEvent(
        provider="test-provider",
        event_id="evt-002",
        event_type="payment.completed",
        payload={
            "business_id": "attacker-business",
            "payment": {
                "status": "paid",
            },
        },
        received_at=datetime(
            2026,
            9,
            1,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    verifier = SemanticPaymentVerifier(
        FakeExtractor(facts)
    )

    result = verifier.verify(
        event,
        make_request(),
    )

    assert result.status is PaymentVerificationStatus.VERIFIED
    assert result.purchase.business_id == "business-001"


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_invalid_expected_amount_is_rejected_at_request_boundary(
    amount,
):
    with pytest.raises((ValueError, TypeError)):
        PaymentVerificationRequest(
            business_id="business-001",
            expected_amount=amount,
            expected_currency="ZAR",
            requested_at=datetime.now(timezone.utc),
        )


def test_nan_payment_amount_is_rejected():
    with pytest.raises(ValueError):
        make_facts(amount=Decimal("NaN"))


def test_infinite_payment_amount_is_rejected():
    with pytest.raises(ValueError):
        make_facts(amount=Decimal("Infinity"))


def test_negative_payment_amount_is_rejected():
    with pytest.raises(ValueError):
        make_facts(amount=Decimal("-1.00"))


def test_currency_is_case_sensitive():
    with pytest.raises(ValueError):
        make_facts(currency="zar")


def test_currency_substitution_is_rejected():
    result = verify(
        make_facts(currency="USD")
    )

    assert result.status is PaymentVerificationStatus.REJECTED


def test_future_payment_timestamp_is_rejected():
    result = verify(
        make_facts(
            paid_at=datetime(
                2026,
                9,
                1,
                12,
                0,
                1,
                tzinfo=timezone.utc,
            )
        )
    )

    assert result.status is PaymentVerificationStatus.REJECTED


def test_naive_payment_timestamp_is_rejected():
    with pytest.raises(ValueError):
        PaymentFacts(
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
            ),
        )


@pytest.mark.parametrize(
    "status",
    [
        "pending",
        "processing",
        "failed",
        "cancelled",
        "refunded",
        "partially_paid",
        "authorized",
    ],
)
def test_non_final_payment_states_never_create_purchase(status):
    result = verify(
        make_facts(payment_status=status)
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.purchase is None


def test_extractor_contract_violation_is_not_silently_accepted():
    class InvalidExtractor(PaymentFactExtractor):
        def extract(self, event):
            return {
                "business_id": "business-001",
                "amount": Decimal("300.00"),
            }

    verifier = SemanticPaymentVerifier(
        InvalidExtractor()
    )

    with pytest.raises(TypeError):
        verifier.verify(
            make_event(),
            make_request(),
        )


def test_extractor_failure_is_not_converted_into_fake_success():
    verifier = SemanticPaymentVerifier(
        RaisingExtractor()
    )

    with pytest.raises(RuntimeError, match="provider parsing failure"):
        verifier.verify(
            make_event(),
            make_request(),
        )


def test_verification_has_no_commercial_side_effects():
    result = verify(make_facts())

    purchase = result.purchase

    assert isinstance(purchase, VerifiedPurchase)

    forbidden_names = {
        "activate_business",
        "record_paid_business",
        "commit",
        "rollback",
        "process",
        "save",
    }

    assert forbidden_names.isdisjoint(
        set(dir(purchase))
    )


def test_verifier_does_not_treat_event_id_as_duplicate_logic():
    first = verify(make_facts())

    second = verify(make_facts())

    assert first.status is PaymentVerificationStatus.VERIFIED
    assert second.status is PaymentVerificationStatus.VERIFIED

    assert (
        first.purchase.provider_event_id
        == second.purchase.provider_event_id
    )


def test_duplicate_handling_remains_outside_verification():
    assert not hasattr(
        PaymentVerificationStatus,
        "DUPLICATE",
    )


def test_verified_purchase_preserves_provider_event_identity():
    result = verify(make_facts())

    assert result.purchase.provider == "test-provider"
    assert result.purchase.provider_event_id == "evt-001"


def test_request_business_identity_is_authoritative():
    request = make_request()

    attacker_facts = make_facts(
        business_id="attacker-business"
    )

    result = verify(
        attacker_facts,
        request=request,
    )

    assert result.status is PaymentVerificationStatus.REJECTED
    assert result.purchase is None


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("0"),
        Decimal("-0.01"),
        Decimal("-100.00"),
    ],
)
def test_payment_facts_reject_invalid_amounts(amount):
    with pytest.raises((ValueError, TypeError)):
        PaymentFacts(
            business_id="business-001",
            amount=amount,
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


def test_payment_facts_rejects_non_decimal_amount():
    with pytest.raises(TypeError):
        PaymentFacts(
            business_id="business-001",
            amount=300.00,
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


@pytest.mark.parametrize(
    "currency",
    [
        "",
        "zar",
        "ZAR ",
        "ZAR1",
        "ZA",
        "ZARAA",
    ],
)
def test_payment_facts_reject_invalid_currency(currency):
    with pytest.raises((ValueError, TypeError)):
        PaymentFacts(
            business_id="business-001",
            amount=Decimal("300.00"),
            currency=currency,
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


def test_payment_facts_rejects_naive_timestamp():
    with pytest.raises(ValueError):
        PaymentFacts(
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
            ),
        )
