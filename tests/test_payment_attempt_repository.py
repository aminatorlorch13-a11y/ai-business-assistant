from datetime import datetime, timedelta, timezone
from decimal import Decimal

import sqlite3

import pytest

from app.persistence.database import SQLiteDatabase
from app.persistence.payment_attempt_repository import (
    SQLitePaymentAttemptRepository,
)
from app.persistence.subscription_repository import SQLiteSubscriptionRepository


NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
CHECKOUT_URL = "https://checkout.example/session/123"


@pytest.fixture
def setup(tmp_path):
    database = SQLiteDatabase(tmp_path / "payments.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        for business_id in ("business-a", "business-b"):
            connection.execute(
                """INSERT INTO businesses(
                    business_id, name, owner_name, assistant_name, assistant_voice
                ) VALUES (?, ?, ?, ?, ?)""",
                (business_id, business_id, "Owner", "Assistant", "male"),
            )
            connection.execute(
                "INSERT INTO commercial_states(business_id, status) VALUES (?, ?)",
                (business_id, "trial"),
            )

    subscriptions = SQLiteSubscriptionRepository(database)
    subscriptions.create_plan(
        plan_id="monthly",
        name="Monthly",
        amount=Decimal("199.00"),
        currency="ZAR",
        interval_months=1,
        now=NOW,
    )
    subscriptions.create_subscription(
        subscription_id="sub-a",
        business_id="business-a",
        plan_id="monthly",
        now=NOW,
    )
    subscriptions.create_subscription(
        subscription_id="sub-b",
        business_id="business-b",
        plan_id="monthly",
        now=NOW,
    )

    return database, SQLitePaymentAttemptRepository(database)


def create_attempt(repository, **overrides):
    values = {
        "attempt_id": "attempt-a",
        "business_id": "business-a",
        "subscription_id": "sub-a",
        "provider": "provider-a",
        "idempotency_key": "request-a",
        "amount": Decimal("199.00"),
        "currency": "ZAR",
        "now": NOW,
    }
    values.update(overrides)
    return repository.create_attempt(**values)


def test_create_and_retrieve_payment_attempt(setup):
    _, repository = setup

    created = create_attempt(repository)
    retrieved = repository.get_attempt("attempt-a")

    assert created["attempt_id"] == "attempt-a"
    assert created["business_id"] == "business-a"
    assert created["subscription_id"] == "sub-a"
    assert created["amount"] == "199.00"
    assert created["currency"] == "ZAR"
    assert created["status"] == "created"
    assert retrieved == created


def test_get_by_idempotency_key(setup):
    _, repository = setup
    create_attempt(repository)

    result = repository.get_by_idempotency_key(
        business_id="business-a",
        idempotency_key="request-a",
    )

    assert result is not None
    assert result["attempt_id"] == "attempt-a"


def test_identical_idempotent_request_returns_original_attempt(setup):
    _, repository = setup
    original = create_attempt(repository)

    repeated = create_attempt(
        repository,
        attempt_id="different-attempt-id",
    )

    assert repeated["attempt_id"] == original["attempt_id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "different-provider"},
        {"amount": Decimal("250.00")},
        {"currency": "USD"},
    ],
)
def test_idempotency_key_cannot_be_reused_for_different_payment(
    setup, overrides
):
    _, repository = setup
    create_attempt(repository)

    with pytest.raises(ValueError, match="Idempotency key"):
        create_attempt(repository, **overrides)



def test_idempotency_key_cannot_be_reused_for_another_subscription(setup):
    database, repository = setup
    create_attempt(repository)

    subscriptions = SQLiteSubscriptionRepository(database)
    subscriptions.cancel_subscription(
        subscription_id="sub-a",
        cancelled_at=NOW,
        at_period_end=False,
    )
    subscriptions.create_subscription(
        subscription_id="sub-a2",
        business_id="business-a",
        plan_id="monthly",
        now=NOW,
    )

    with pytest.raises(ValueError, match="Idempotency key"):
        create_attempt(
            repository,
            attempt_id="attempt-a2",
            subscription_id="sub-a2",
        )


def test_subscription_must_belong_to_business(setup):
    _, repository = setup

    with pytest.raises(ValueError, match="does not belong"):
        create_attempt(repository, business_id="business-b")


def test_open_attempt_lookup_is_tenant_scoped(setup):
    _, repository = setup
    create_attempt(repository)

    found = repository.find_open_attempt(
        business_id="business-a",
        subscription_id="sub-a",
    )
    hidden = repository.find_open_attempt(
        business_id="business-b",
        subscription_id="sub-a",
    )

    assert found["attempt_id"] == "attempt-a"
    assert hidden is None


def test_checkout_details_are_recorded_and_cannot_be_replaced(setup):
    _, repository = setup
    create_attempt(repository)

    result = repository.record_checkout(
        attempt_id="attempt-a",
        business_id="business-a",
        checkout_url=CHECKOUT_URL,
        provider_checkout_id="checkout-123",
        now=NOW,
    )

    assert result["status"] == "checkout_created"
    assert result["checkout_url"] == CHECKOUT_URL
    assert result["provider_checkout_id"] == "checkout-123"

    repeated = repository.record_checkout(
        attempt_id="attempt-a",
        business_id="business-a",
        checkout_url=CHECKOUT_URL,
        provider_checkout_id="checkout-123",
        now=NOW,
    )
    assert repeated == result

    with pytest.raises(ValueError, match="cannot be replaced"):
        repository.record_checkout(
            attempt_id="attempt-a",
            business_id="business-a",
            checkout_url="https://checkout.example/another-session",
            provider_checkout_id="checkout-456",
            now=NOW,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://checkout.example/session",
        "javascript:alert(1)",
        "https:///missing-host",
        "https://user:password@checkout.example/session",
        "https://checkout.example/session#fragment",
        "not-a-url",
        "",
    ],
)
def test_invalid_checkout_urls_are_rejected(setup, url):
    _, repository = setup
    create_attempt(repository)

    with pytest.raises(ValueError, match="checkout_url"):
        repository.record_checkout(
            attempt_id="attempt-a",
            business_id="business-a",
            checkout_url=url,
            provider_checkout_id=None,
            now=NOW,
        )


def test_duplicate_provider_checkout_identifier_is_rejected(setup):
    _, repository = setup
    create_attempt(repository)

    repository.record_checkout(
        attempt_id="attempt-a",
        business_id="business-a",
        checkout_url=CHECKOUT_URL,
        provider_checkout_id="shared-checkout-id",
        now=NOW,
    )

    create_attempt(
        repository,
        attempt_id="attempt-b",
        business_id="business-b",
        subscription_id="sub-b",
        idempotency_key="request-b",
    )

    with pytest.raises(ValueError, match="already in use"):
        repository.record_checkout(
            attempt_id="attempt-b",
            business_id="business-b",
            checkout_url="https://checkout.example/other",
            provider_checkout_id="shared-checkout-id",
            now=NOW,
        )

    assert repository.get_attempt("attempt-b")["status"] == "created"


def test_duplicate_provider_payment_identifier_is_protected_by_schema(setup):
    database, repository = setup
    create_attempt(repository)

    with database.transaction() as connection:
        connection.execute(
            """UPDATE payment_attempts
               SET provider_payment_id = ?
               WHERE attempt_id = ?""",
            ("payment-shared", "attempt-a"),
        )

    create_attempt(
        repository,
        attempt_id="attempt-b",
        idempotency_key="request-b",
    )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """UPDATE payment_attempts
                   SET provider_payment_id = ?
                   WHERE attempt_id = ?""",
                ("payment-shared", "attempt-b"),
            )


def test_status_transitions_and_open_attempt_lookup(setup):
    _, repository = setup
    create_attempt(repository)

    pending = repository.update_status(
        attempt_id="attempt-a",
        business_id="business-a",
        status="pending",
        now=NOW,
    )
    assert pending["status"] == "pending"

    failed = repository.update_status(
        attempt_id="attempt-a",
        business_id="business-a",
        status="failed",
        failure_reason="Provider reported payment failure.",
        now=NOW + timedelta(minutes=1),
    )
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "Provider reported payment failure."

    assert repository.find_open_attempt(
        business_id="business-a",
        subscription_id="sub-a",
    ) is None


def test_invalid_status_transition_is_rejected(setup):
    _, repository = setup
    create_attempt(repository)

    repository.update_status(
        attempt_id="attempt-a",
        business_id="business-a",
        status="failed",
        now=NOW,
    )

    with pytest.raises(ValueError, match="Invalid payment attempt transition"):
        repository.update_status(
            attempt_id="attempt-a",
            business_id="business-a",
            status="pending",
            now=NOW,
        )


def test_ordinary_repository_cannot_mark_payment_settled(setup):
    _, repository = setup
    create_attempt(repository)

    with pytest.raises(ValueError, match="verified-purchase boundary"):
        repository.update_status(
            attempt_id="attempt-a",
            business_id="business-a",
            status="settled",
            now=NOW,
        )

    assert repository.get_attempt("attempt-a")["status"] == "created"


def test_tenant_cannot_record_checkout_or_update_another_business_attempt(setup):
    _, repository = setup
    create_attempt(repository)

    with pytest.raises(ValueError, match="does not belong"):
        repository.record_checkout(
            attempt_id="attempt-a",
            business_id="business-b",
            checkout_url=CHECKOUT_URL,
            provider_checkout_id=None,
            now=NOW,
        )

    with pytest.raises(ValueError, match="does not belong"):
        repository.update_status(
            attempt_id="attempt-a",
            business_id="business-b",
            status="failed",
            now=NOW,
        )

    assert repository.get_attempt("attempt-a")["status"] == "created"


def test_expiry_is_persisted_and_attempt_can_expire(setup):
    _, repository = setup
    expiry = NOW + timedelta(hours=1)

    created = create_attempt(repository, expires_at=expiry)
    assert created["expires_at"] == expiry.isoformat()

    expired = repository.update_status(
        attempt_id="attempt-a",
        business_id="business-a",
        status="expired",
        now=expiry,
    )
    assert expired["status"] == "expired"


def test_failed_insert_rolls_back_without_partial_attempt(setup):
    _, repository = setup
    create_attempt(repository)

    with pytest.raises(ValueError, match="could not be created"):
        create_attempt(
            repository,
            attempt_id="attempt-a",
            idempotency_key="different-request",
        )

    assert repository.get_by_idempotency_key(
        business_id="business-a",
        idempotency_key="different-request",
    ) is None


def test_invalid_amount_and_currency_are_rejected(setup):
    _, repository = setup

    with pytest.raises(ValueError, match="greater than zero"):
        create_attempt(repository, amount=Decimal("0"))

    with pytest.raises(ValueError, match="currency"):
        create_attempt(repository, currency="zar")
