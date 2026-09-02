from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.in_memory_commercial_store import InMemoryCommercialStore
from app.commercial.in_memory_transaction_factory import (
    InMemoryCommercialTransactionFactory,
)
from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_application import (
    CommercialPurchaseService,
    PurchaseApplicationResult,
)


def make_purchase(
    *,
    provider: str = "test_provider",
    event_id: str = "evt_123",
    business_id: str = "business_123",
) -> VerifiedPurchase:
    return VerifiedPurchase(
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


class TrackingTransaction:
    """Minimal transaction fake for application-service behavior tests."""

    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.events = []
        self.records = []
        self.activated_business_ids = []
        self.paid_business_ids = []
        self.committed = False
        self.rolled_back = False

    def record_purchase_once(self, record):
        self.events.append("record")

        if self.duplicate:
            return False

        self.records.append(record)
        return True

    def activate_business(self, business_id):
        self.events.append("activate")
        self.activated_business_ids.append(business_id)

    def record_paid_business(self, business_id):
        self.events.append("launch")
        self.paid_business_ids.append(business_id)

    def commit(self):
        self.events.append("commit")
        self.committed = True

    def rollback(self):
        self.events.append("rollback")
        self.rolled_back = True


class FailingTransaction(TrackingTransaction):
    """Transaction fake that injects one controlled failure."""

    def __init__(self, *, fail_on: str) -> None:
        super().__init__()
        self.fail_on = fail_on

    def record_purchase_once(self, record):
        self.events.append("record")

        if self.fail_on == "record":
            raise RuntimeError("record failure")

        self.records.append(record)
        return True

    def activate_business(self, business_id):
        self.events.append("activate")
        self.activated_business_ids.append(business_id)

        if self.fail_on == "activate":
            raise RuntimeError("activation failure")

    def record_paid_business(self, business_id):
        self.events.append("launch")
        self.paid_business_ids.append(business_id)

        if self.fail_on == "launch":
            raise RuntimeError("launch failure")

    def commit(self):
        self.events.append("commit")

        if self.fail_on == "commit":
            raise RuntimeError("commit failure")

        self.committed = True

    def rollback(self):
        self.events.append("rollback")
        self.rolled_back = True


class FakeTransactionFactory:
    def __init__(self, transaction) -> None:
        self.transaction = transaction
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.transaction


def make_service(
    *,
    transaction=None,
):
    transaction = transaction or TrackingTransaction()
    factory = FakeTransactionFactory(transaction)
    service = CommercialPurchaseService(
        transaction_factory=factory,
    )
    return service, transaction, factory


def test_new_purchase_is_processed():
    service, transaction, factory = make_service()

    result = service.process(
        make_purchase(),
        datetime.now(timezone.utc),
    )

    assert result.processed is True
    assert result.duplicate is False
    assert len(transaction.records) == 1
    assert transaction.activated_business_ids == ["business_123"]
    assert transaction.paid_business_ids == ["business_123"]
    assert transaction.events == [
        "record",
        "activate",
        "launch",
        "commit",
    ]
    assert factory.begin_count == 1


def test_duplicate_purchase_has_no_commercial_side_effects():
    transaction = TrackingTransaction(duplicate=True)
    service, transaction, factory = make_service(
        transaction=transaction,
    )

    result = service.process(
        make_purchase(),
        datetime.now(timezone.utc),
    )

    assert result.processed is False
    assert result.duplicate is True
    assert transaction.records == []
    assert transaction.activated_business_ids == []
    assert transaction.paid_business_ids == []
    assert transaction.events == [
        "record",
        "rollback",
    ]
    assert factory.begin_count == 1


def test_business_identity_is_preserved():
    service, transaction, _ = make_service()

    service.process(
        make_purchase(
            business_id="business_secure",
        ),
        datetime.now(timezone.utc),
    )

    assert transaction.activated_business_ids == ["business_secure"]
    assert transaction.paid_business_ids == ["business_secure"]


def test_provider_identity_is_preserved():
    service, _, _ = make_service()

    purchase = make_purchase(
        provider="provider_secure",
        event_id="event_secure",
    )

    result = service.process(
        purchase,
        datetime.now(timezone.utc),
    )

    assert result.provider == "provider_secure"
    assert result.provider_event_id == "event_secure"


def test_purchase_must_be_verified_purchase():
    service, _, _ = make_service()

    with pytest.raises(TypeError):
        service.process(
            object(),
            datetime.now(timezone.utc),
        )


def test_recorded_at_is_validated_by_purchase_record():
    service, _, _ = make_service()

    with pytest.raises(TypeError):
        service.process(
            make_purchase(),
            "not-a-datetime",
        )


def test_activation_happens_before_launch_update():
    transaction = TrackingTransaction()
    service, transaction, _ = make_service(
        transaction=transaction,
    )

    service.process(
        make_purchase(),
        datetime.now(timezone.utc),
    )

    assert transaction.events == [
        "record",
        "activate",
        "launch",
        "commit",
    ]


def test_duplicate_does_not_activate_another_business():
    transaction = TrackingTransaction(duplicate=True)
    service, transaction, _ = make_service(
        transaction=transaction,
    )

    service.process(
        make_purchase(
            business_id="business_attacker",
        ),
        datetime.now(timezone.utc),
    )

    assert transaction.activated_business_ids == []
    assert transaction.paid_business_ids == []


def test_result_is_immutable():
    result = PurchaseApplicationResult(
        business_id="business_123",
        provider="test_provider",
        provider_event_id="evt_123",
        processed=True,
        duplicate=False,
    )

    with pytest.raises(AttributeError):
        result.processed = False


def test_result_rejects_equal_processed_and_duplicate_states():
    with pytest.raises(ValueError):
        PurchaseApplicationResult(
            business_id="business_123",
            provider="test_provider",
            provider_event_id="evt_123",
            processed=True,
            duplicate=True,
        )


def test_result_rejects_non_boolean_processed():
    with pytest.raises(TypeError):
        PurchaseApplicationResult(
            business_id="business_123",
            provider="test_provider",
            provider_event_id="evt_123",
            processed=1,
            duplicate=False,
        )


def test_result_rejects_non_boolean_duplicate():
    with pytest.raises(TypeError):
        PurchaseApplicationResult(
            business_id="business_123",
            provider="test_provider",
            provider_event_id="evt_123",
            processed=False,
            duplicate=1,
        )


def test_transaction_factory_creates_fresh_transactions_over_shared_store():
    store = InMemoryCommercialStore()
    factory = InMemoryCommercialTransactionFactory(store)

    transaction_a = factory.begin()
    transaction_b = factory.begin()

    assert transaction_a is not transaction_b


def test_purchase_service_transaction_success_commits_once():
    transaction = TrackingTransaction()
    service, transaction, factory = make_service(
        transaction=transaction,
    )

    result = service.process(
        make_purchase(),
        datetime.now(timezone.utc),
    )

    assert result.processed is True
    assert result.duplicate is False
    assert transaction.events == [
        "record",
        "activate",
        "launch",
        "commit",
    ]
    assert factory.begin_count == 1


def test_purchase_service_transaction_duplicate_rolls_back():
    transaction = TrackingTransaction(duplicate=True)
    service, transaction, factory = make_service(
        transaction=transaction,
    )

    result = service.process(
        make_purchase(),
        datetime.now(timezone.utc),
    )

    assert result.processed is False
    assert result.duplicate is True
    assert transaction.events == [
        "record",
        "rollback",
    ]
    assert factory.begin_count == 1


@pytest.mark.parametrize(
    ("failure", "expected_events"),
    [
        (
            "record",
            ["record", "rollback"],
        ),
        (
            "activate",
            ["record", "activate", "rollback"],
        ),
        (
            "launch",
            ["record", "activate", "launch", "rollback"],
        ),
    ],
)
def test_purchase_service_pre_commit_failures_rollback(
    failure,
    expected_events,
):
    transaction = FailingTransaction(fail_on=failure)
    service, transaction, factory = make_service(
        transaction=transaction,
    )

    with pytest.raises(RuntimeError):
        service.process(
            make_purchase(),
            datetime.now(timezone.utc),
        )

    assert transaction.events == expected_events
    assert transaction.committed is False
    assert transaction.rolled_back is True
    assert factory.begin_count == 1


def test_purchase_service_commit_failure_is_not_double_rolled_back():
    transaction = FailingTransaction(fail_on="commit")
    service, transaction, factory = make_service(
        transaction=transaction,
    )

    with pytest.raises(RuntimeError, match="commit failure"):
        service.process(
            make_purchase(),
            datetime.now(timezone.utc),
        )

    assert transaction.events == [
        "record",
        "activate",
        "launch",
        "commit",
    ]
    assert transaction.rolled_back is False
    assert factory.begin_count == 1


def test_purchase_service_with_real_in_memory_transaction_persists_all_effects():
    store = InMemoryCommercialStore()
    factory = InMemoryCommercialTransactionFactory(store)
    service = CommercialPurchaseService(
        transaction_factory=factory,
    )

    purchase = make_purchase()

    result = service.process(
        purchase,
        datetime.now(timezone.utc),
    )

    assert result.processed is True
    assert result.duplicate is False

    key = (
        purchase.provider,
        purchase.provider_event_id,
    )

    assert key in store.purchase_records
    assert purchase.business_id in store.active_businesses
    assert purchase.business_id in store.paid_businesses


def test_purchase_service_with_real_in_memory_transaction_is_idempotent():
    store = InMemoryCommercialStore()
    factory = InMemoryCommercialTransactionFactory(store)
    service = CommercialPurchaseService(
        transaction_factory=factory,
    )

    purchase = make_purchase()
    recorded_at = datetime.now(timezone.utc)

    first = service.process(
        purchase,
        recorded_at,
    )

    second = service.process(
        purchase,
        recorded_at,
    )

    assert first.processed is True
    assert first.duplicate is False

    assert second.processed is False
    assert second.duplicate is True

    assert len(store.purchase_records) == 1
    assert store.active_businesses == {"business_123"}
    assert store.paid_businesses == {"business_123"}
