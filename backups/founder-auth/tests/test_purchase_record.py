from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord


def make_purchase() -> VerifiedPurchase:
    return VerifiedPurchase(
        provider="test_provider",
        provider_event_id="evt_123",
        business_id="business_123",
        amount=Decimal("499.99"),
        currency="ZAR",
        paid_at=datetime(
            2026,
            8,
            31,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_record() -> PurchaseRecord:
    return PurchaseRecord(
        purchase=make_purchase(),
        recorded_at=datetime(
            2026,
            8,
            31,
            12,
            1,
            tzinfo=timezone.utc,
        ),
    )


def test_valid_record_is_created():
    record = make_record()

    assert record.purchase == make_purchase()
    assert record.provider == "test_provider"
    assert record.provider_event_id == "evt_123"
    assert record.business_id == "business_123"


def test_record_is_immutable():
    record = make_record()

    with pytest.raises(AttributeError):
        record.recorded_at = datetime.now(timezone.utc)


def test_purchase_must_be_verified_purchase():
    with pytest.raises(TypeError):
        PurchaseRecord(
            purchase=object(),
            recorded_at=datetime.now(timezone.utc),
        )


def test_recorded_at_must_be_datetime():
    with pytest.raises(TypeError):
        PurchaseRecord(
            purchase=make_purchase(),
            recorded_at="2026-08-31T12:01:00Z",
        )


def test_recorded_at_must_be_timezone_aware():
    with pytest.raises(ValueError):
        PurchaseRecord(
            purchase=make_purchase(),
            recorded_at=datetime(
                2026,
                8,
                31,
                12,
                1,
            ),
        )



def test_record_preserves_verified_purchase_identity():
    record = make_record()

    assert record.provider == record.purchase.provider
    assert (
        record.provider_event_id
        == record.purchase.provider_event_id
    )
    assert record.business_id == record.purchase.business_id


def test_record_contains_no_payment_credentials():
    record = make_record()

    forbidden_fields = {
        "bank_account",
        "account_number",
        "card_number",
        "cvv",
        "password",
        "secret",
        "api_key",
    }

    assert forbidden_fields.isdisjoint(vars(record))


def test_record_contains_no_activation_state():
    record = make_record()

    forbidden_fields = {
        "active",
        "status",
        "entitlements",
        "capabilities",
        "pricing",
        "launch_program",
    }

    assert forbidden_fields.isdisjoint(vars(record))
