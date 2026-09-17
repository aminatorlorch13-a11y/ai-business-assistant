from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.in_memory_purchase_store import InMemoryPurchaseStore
from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord


def make_record(
    *,
    provider: str = "test_provider",
    event_id: str = "evt_123",
    business_id: str = "business_123",
) -> PurchaseRecord:
    purchase = VerifiedPurchase(
        provider=provider,
        provider_event_id=event_id,
        business_id=business_id,
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

    return PurchaseRecord(
        purchase=purchase,
        recorded_at=datetime(
            2026,
            8,
            31,
            12,
            1,
            tzinfo=timezone.utc,
        ),
    )


def test_new_store_has_no_records():
    store = InMemoryPurchaseStore()

    assert store.get(
        "test_provider",
        "evt_123",
    ) is None


def test_saved_record_can_be_retrieved():
    store = InMemoryPurchaseStore()
    record = make_record()

    store.save(record)

    assert store.get(
        "test_provider",
        "evt_123",
    ) == record


def test_save_preserves_exact_record_identity():
    store = InMemoryPurchaseStore()
    record = make_record()

    store.save(record)

    retrieved = store.get(
        record.provider,
        record.provider_event_id,
    )

    assert retrieved is record


def test_duplicate_provider_event_is_rejected():
    store = InMemoryPurchaseStore()

    first = make_record()
    second = make_record()

    store.save(first)

    with pytest.raises(ValueError):
        store.save(second)


def test_duplicate_does_not_replace_original_record():
    store = InMemoryPurchaseStore()

    first = make_record(
        business_id="business_original",
    )
    duplicate = make_record(
        business_id="business_attacker",
    )

    store.save(first)

    with pytest.raises(ValueError):
        store.save(duplicate)

    assert store.get(
        "test_provider",
        "evt_123",
    ) is first


def test_same_event_id_from_different_provider_is_distinct():
    store = InMemoryPurchaseStore()

    first = make_record(
        provider="provider_a",
        event_id="evt_123",
    )
    second = make_record(
        provider="provider_b",
        event_id="evt_123",
    )

    store.save(first)
    store.save(second)

    assert store.get(
        "provider_a",
        "evt_123",
    ) is first

    assert store.get(
        "provider_b",
        "evt_123",
    ) is second


def test_same_provider_can_have_different_event_ids():
    store = InMemoryPurchaseStore()

    first = make_record(
        event_id="evt_123",
    )
    second = make_record(
        event_id="evt_456",
    )

    store.save(first)
    store.save(second)

    assert store.get(
        "test_provider",
        "evt_123",
    ) is first

    assert store.get(
        "test_provider",
        "evt_456",
    ) is second


@pytest.mark.parametrize(
    "provider",
    ["", "   "],
)
def test_get_rejects_empty_provider(provider):
    store = InMemoryPurchaseStore()

    with pytest.raises(ValueError):
        store.get(provider, "evt_123")


def test_get_rejects_non_string_provider():
    store = InMemoryPurchaseStore()

    with pytest.raises(TypeError):
        store.get(123, "evt_123")


@pytest.mark.parametrize(
    "event_id",
    ["", "   "],
)
def test_get_rejects_empty_event_id(event_id):
    store = InMemoryPurchaseStore()

    with pytest.raises(ValueError):
        store.get("test_provider", event_id)


def test_get_rejects_non_string_event_id():
    store = InMemoryPurchaseStore()

    with pytest.raises(TypeError):
        store.get("test_provider", 123)


def test_save_rejects_non_purchase_record():
    store = InMemoryPurchaseStore()

    with pytest.raises(TypeError):
        store.save(object())


def test_store_does_not_expose_mutable_record_collection():
    store = InMemoryPurchaseStore()
    record = make_record()

    store.save(record)

    assert not hasattr(store, "records")


def test_business_identity_is_preserved():
    store = InMemoryPurchaseStore()
    record = make_record(
        business_id="business_123",
    )

    store.save(record)

    retrieved = store.get(
        "test_provider",
        "evt_123",
    )

    assert retrieved is not None
    assert retrieved.business_id == "business_123"


def test_duplicate_event_across_businesses_is_still_rejected():
    store = InMemoryPurchaseStore()

    first = make_record(
        business_id="business_a",
    )
    second = make_record(
        business_id="business_b",
    )

    store.save(first)

    with pytest.raises(ValueError):
        store.save(second)

    assert store.get(
        "test_provider",
        "evt_123",
    ) is first
