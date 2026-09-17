from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase


def make_purchase(**overrides) -> VerifiedPurchase:
    values = {
        "provider": "test_provider",
        "provider_event_id": "evt_123",
        "business_id": "business_123",
        "amount": Decimal("499.99"),
        "currency": "ZAR",
        "paid_at": datetime(
            2026,
            8,
            31,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    }

    values.update(overrides)

    return VerifiedPurchase(**values)


def test_valid_purchase_is_created():
    purchase = make_purchase()

    assert purchase.provider == "test_provider"
    assert purchase.provider_event_id == "evt_123"
    assert purchase.business_id == "business_123"
    assert purchase.amount == Decimal("499.99")
    assert purchase.currency == "ZAR"
    assert purchase.paid_at.tzinfo is not None


def test_purchase_is_immutable():
    purchase = make_purchase()

    with pytest.raises(AttributeError):
        purchase.amount = Decimal("1000.00")


@pytest.mark.parametrize(
    "field",
    [
        "provider",
        "provider_event_id",
        "business_id",
    ],
)
def test_required_string_fields_must_be_non_empty(field):
    with pytest.raises(ValueError):
        make_purchase(**{field: "   "})


@pytest.mark.parametrize(
    "field",
    [
        "provider",
        "provider_event_id",
        "business_id",
    ],
)
def test_required_string_fields_must_be_strings(field):
    with pytest.raises(TypeError):
        make_purchase(**{field: 123})


def test_amount_must_be_decimal():
    with pytest.raises(TypeError):
        make_purchase(amount=499.99)


def test_bool_amount_is_rejected():
    with pytest.raises(TypeError):
        make_purchase(amount=True)


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),
        Decimal("-0.01"),
        Decimal("-100"),
    ],
)
def test_amount_must_be_greater_than_zero(amount):
    with pytest.raises(ValueError):
        make_purchase(amount=amount)


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_amount_must_be_finite(amount):
    with pytest.raises(ValueError):
        make_purchase(amount=amount)


@pytest.mark.parametrize(
    "currency",
    [
        "",
        " ",
        "zar",
        "ZaR",
        "ZARR",
        "ZA",
        "123",
        "Z@R",
    ],
)
def test_currency_must_be_three_uppercase_letters(currency):
    with pytest.raises(ValueError):
        make_purchase(currency=currency)


def test_currency_must_be_a_string():
    with pytest.raises(TypeError):
        make_purchase(currency=123)


def test_paid_at_must_be_datetime():
    with pytest.raises(TypeError):
        make_purchase(paid_at="2026-08-31T12:00:00Z")


def test_paid_at_must_be_timezone_aware():
    with pytest.raises(ValueError):
        make_purchase(
            paid_at=datetime(
                2026,
                8,
                31,
                12,
                0,
            )
        )



def test_provider_event_id_is_part_of_purchase_identity():
    first = make_purchase(
        provider_event_id="evt_123"
    )
    second = make_purchase(
        provider_event_id="evt_456"
    )

    assert first.provider_event_id != second.provider_event_id


def test_same_event_id_can_exist_as_an_immutable_fact():
    first = make_purchase(
        provider_event_id="evt_same"
    )
    second = make_purchase(
        provider_event_id="evt_same"
    )

    assert first == second


def test_purchase_contains_no_payment_credentials():
    purchase = make_purchase()

    forbidden_fields = {
        "bank_account",
        "account_number",
        "card_number",
        "cvv",
        "password",
        "secret",
        "api_key",
    }

    assert forbidden_fields.isdisjoint(vars(purchase))


def test_purchase_contains_no_commercial_activation_state():
    purchase = make_purchase()

    forbidden_fields = {
        "active",
        "status",
        "entitlements",
        "capabilities",
        "pricing",
        "launch_program",
    }

    assert forbidden_fields.isdisjoint(vars(purchase))


def test_purchase_contains_no_external_side_effect_methods():
    forbidden_methods = {
        "activate",
        "process",
        "charge",
        "refund",
        "update_launch_program",
        "record_purchase",
    }

    actual_methods = {
        name
        for name in dir(VerifiedPurchase)
        if not name.startswith("_")
    }

    assert forbidden_methods.isdisjoint(actual_methods)
