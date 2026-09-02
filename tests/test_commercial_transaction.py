from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.in_memory_commercial_store import (
    InMemoryCommercialStore,
)
from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.commercial.transaction import CommercialTransaction
from app.commercial.in_memory_transaction import InMemoryCommercialTransaction


def make_record():
    purchase = VerifiedPurchase(
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


class FakeTransaction:
    def record_purchase_once(self, record):
        return True

    def activate_business(self, business_id):
        pass

    def record_paid_business(self, business_id):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


def test_fake_transaction_satisfies_protocol():
    transaction = FakeTransaction()

    assert isinstance(
        transaction,
        CommercialTransaction,
    )


def test_transaction_can_record_purchase_once():
    transaction = FakeTransaction()

    assert transaction.record_purchase_once(
        make_record(),
    ) is True


def test_transaction_exposes_atomic_commercial_operations():
    transaction = FakeTransaction()

    assert callable(transaction.record_purchase_once)
    assert callable(transaction.activate_business)
    assert callable(transaction.record_paid_business)
    assert callable(transaction.commit)
    assert callable(transaction.rollback)


def test_real_transaction_stages_changes_until_commit():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)
    record = make_record()

    assert transaction.record_purchase_once(record) is True
    transaction.activate_business("business_123")
    transaction.record_paid_business("business_123")

    assert transaction.has_purchase(
        "test_provider",
        "evt_123",
    ) is True
    assert transaction.is_business_active(
        "business_123",
    ) is True
    assert transaction.is_paid_business(
        "business_123",
    ) is True

    transaction.commit()


def test_real_transaction_commit_preserves_all_staged_changes():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)
    record = make_record()

    transaction.record_purchase_once(record)
    transaction.activate_business("business_123")
    transaction.record_paid_business("business_123")
    transaction.commit()

    assert transaction.has_purchase(
        "test_provider",
        "evt_123",
    ) is True
    assert transaction.is_business_active(
        "business_123",
    ) is True
    assert transaction.is_paid_business(
        "business_123",
    ) is True


def test_real_transaction_rollback_discards_all_staged_changes():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)
    record = make_record()

    transaction.record_purchase_once(record)
    transaction.activate_business("business_123")
    transaction.record_paid_business("business_123")

    transaction.rollback()

    assert transaction._staged_purchase_records == {}
    assert transaction._staged_active_businesses == set()
    assert transaction._staged_paid_businesses == set()

    assert store.has_purchase(
        "test_provider",
        "evt_123",
    ) is False
    assert "business_123" not in store.active_businesses
    assert "business_123" not in store.paid_businesses


def test_real_transaction_rejects_duplicate_purchase_event():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)
    record = make_record()

    assert transaction.record_purchase_once(record) is True
    assert transaction.record_purchase_once(record) is False


def test_real_transaction_staged_changes_are_invisible_to_other_transactions():
    store = InMemoryCommercialStore()

    transaction_a = InMemoryCommercialTransaction(store)
    transaction_b = InMemoryCommercialTransaction(store)

    record = make_record()

    assert transaction_a.record_purchase_once(record) is True

    assert store.has_purchase(
        record.provider,
        record.provider_event_id,
    ) is False

    assert transaction_b.record_purchase_once(record) is True
    assert transaction_b.has_purchase(
        record.provider,
        record.provider_event_id,
    ) is True

def test_real_transaction_rejects_duplicate_across_transactions():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()

    first_transaction = InMemoryCommercialTransaction(store)
    record = make_record()

    assert first_transaction.record_purchase_once(record) is True
    first_transaction.commit()

    second_transaction = InMemoryCommercialTransaction(store)

    assert second_transaction.record_purchase_once(record) is False


def test_real_transaction_distinguishes_provider_event_namespaces():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    first = make_record()

    second_purchase = VerifiedPurchase(
        provider="another_provider",
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

    second = PurchaseRecord(
        purchase=second_purchase,
        recorded_at=datetime(
            2026,
            8,
            31,
            12,
            1,
            tzinfo=timezone.utc,
        ),
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)

    assert transaction.record_purchase_once(first) is True
    assert transaction.record_purchase_once(second) is True


def test_real_transaction_cannot_be_reused_after_commit():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)
    transaction.commit()

    with pytest.raises(RuntimeError):
        transaction.activate_business("business_123")


def test_real_transaction_cannot_be_reused_after_rollback():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)
    transaction.rollback()

    with pytest.raises(RuntimeError):
        transaction.record_paid_business("business_123")


class FailingActivateStore(InMemoryCommercialStore):
    def activate_business(self, business_id: str) -> None:
        super().activate_business(business_id)
        raise RuntimeError("activation failure")


class FailingPaidStore(InMemoryCommercialStore):
    def record_paid_business(self, business_id: str) -> None:
        super().record_paid_business(business_id)
        raise RuntimeError("paid-business failure")


def test_real_transaction_commit_is_atomic_when_activation_fails():
    store = FailingActivateStore()
    transaction = InMemoryCommercialTransaction(store)
    record = make_record()

    assert transaction.record_purchase_once(record) is True
    transaction.activate_business(record.business_id)
    transaction.record_paid_business(record.business_id)

    with pytest.raises(RuntimeError, match="activation failure"):
        transaction.commit()

    assert store.purchase_records == {}
    assert store.active_businesses == set()
    assert store.paid_businesses == set()


def test_real_transaction_commit_is_atomic_when_paid_business_recording_fails():
    store = FailingPaidStore()
    transaction = InMemoryCommercialTransaction(store)
    record = make_record()

    assert transaction.record_purchase_once(record) is True
    transaction.activate_business(record.business_id)
    transaction.record_paid_business(record.business_id)

    with pytest.raises(RuntimeError, match="paid-business failure"):
        transaction.commit()

    assert store.purchase_records == {}
    assert store.active_businesses == set()
    assert store.paid_businesses == set()


def test_real_transaction_rejects_invalid_business_id():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)

    with pytest.raises(TypeError):
        transaction.activate_business(123)

    with pytest.raises(ValueError):
        transaction.activate_business("   ")


def test_real_transaction_rejects_invalid_purchase_record():
    from app.commercial.in_memory_transaction import (
        InMemoryCommercialTransaction,
    )

    store = InMemoryCommercialStore()
    transaction = InMemoryCommercialTransaction(store)

    with pytest.raises(TypeError):
        transaction.record_purchase_once("not a record")
