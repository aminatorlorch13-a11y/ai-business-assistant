from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.payment.verification import (
    PaymentVerificationResult,
    PaymentVerificationStatus,
)


def make_purchase():
    return VerifiedPurchase(
        provider="test_provider",
        provider_event_id="evt_123",
        business_id="business_123",
        amount=Decimal("499.99"),
        currency="ZAR",
        paid_at=datetime(
            2026,
            9,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )


@pytest.mark.parametrize(
    "status",
    [
        PaymentVerificationStatus.REJECTED,
        PaymentVerificationStatus.REJECTED,
    ],
)
def test_non_verified_result_requires_reason(status):
    with pytest.raises(ValueError):
        PaymentVerificationResult(status=status)


def test_verified_result_requires_purchase():
    with pytest.raises(ValueError):
        PaymentVerificationResult(
            status=PaymentVerificationStatus.VERIFIED,
        )


def test_verified_result_rejects_reason():
    with pytest.raises(ValueError):
        PaymentVerificationResult(
            status=PaymentVerificationStatus.VERIFIED,
            purchase=make_purchase(),
            reason="should not exist",
        )


def test_non_verified_result_cannot_contain_purchase():
    with pytest.raises(ValueError):
        PaymentVerificationResult(
            status=PaymentVerificationStatus.REJECTED,
            purchase=make_purchase(),
            reason="invalid signature",
        )


def test_verified_result_contains_verified_purchase():
    purchase = make_purchase()

    result = PaymentVerificationResult(
        status=PaymentVerificationStatus.VERIFIED,
        purchase=purchase,
    )

    assert result.status is PaymentVerificationStatus.VERIFIED
    assert result.purchase is purchase
    assert result.reason is None


def test_rejected_result_contains_no_purchase():
    result = PaymentVerificationResult(
        status=PaymentVerificationStatus.REJECTED,
        reason="invalid signature",
    )

    assert result.purchase is None
    assert result.reason == "invalid signature"


def test_duplicate_result_contains_no_purchase():
    result = PaymentVerificationResult(
        status=PaymentVerificationStatus.REJECTED,
        reason="event already processed",
    )

    assert result.purchase is None
    assert result.reason == "event already processed"


def test_result_is_immutable():
    result = PaymentVerificationResult(
        status=PaymentVerificationStatus.REJECTED,
        reason="invalid signature",
    )

    with pytest.raises(AttributeError):
        result.status = PaymentVerificationStatus.VERIFIED


def test_status_is_closed_world():
    with pytest.raises(TypeError):
        PaymentVerificationResult(
            status="verified",
            purchase=make_purchase(),
        )
