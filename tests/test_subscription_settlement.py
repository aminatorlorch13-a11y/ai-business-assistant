from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.subscription_settlement import (
    SQLiteSubscriptionSettlementService,
    _add_calendar_months,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.subscription_repository import SQLiteSubscriptionRepository


NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path):
    database = SQLiteDatabase(tmp_path / "settlement.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES ('business-a', 'Business A', 'Owner', 'Assistant', 'male')
            """
        )
        connection.execute(
            "INSERT INTO commercial_states(business_id, status) VALUES ('business-a', 'trial')"
        )
        connection.execute(
            "INSERT INTO users(user_id, display_name, email) VALUES ('owner-a', 'Owner', 'owner@example.test')"
        )

    repository = SQLiteSubscriptionRepository(database)
    repository.create_plan(
        plan_id="monthly",
        name="Monthly",
        amount=Decimal("199.00"),
        currency="ZAR",
        interval_months=1,
        now=NOW,
    )
    repository.create_subscription(
        subscription_id="sub-a",
        business_id="business-a",
        plan_id="monthly",
        now=NOW,
    )

    return database, repository, SQLiteSubscriptionSettlementService(database)


def purchase(
    event_id="event-1",
    *,
    business_id="business-a",
    amount=Decimal("199.00"),
    currency="ZAR",
    paid_at=NOW,
):
    return VerifiedPurchase(
        provider="test-provider",
        provider_event_id=event_id,
        business_id=business_id,
        amount=amount,
        currency=currency,
        paid_at=paid_at,
    )


def counts(database):
    with database.connection() as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "purchase_records",
                "subscription_billing_periods",
                "paid_business_ledger",
            )
        }


def test_settlement_atomically_records_payment_period_and_access(setup):
    database, _, service = setup

    result = service.settle(
        subscription_id="sub-a",
        purchase=purchase(),
        recorded_at=NOW,
    )

    assert result.processed is True
    assert result.duplicate is False
    assert result.period_start == NOW
    assert result.period_end == datetime(2026, 12, 12, 12, 0, tzinfo=timezone.utc)

    with database.connection() as connection:
        subscription = connection.execute(
            "SELECT status, current_period_start, current_period_end "
            "FROM business_subscriptions WHERE subscription_id = 'sub-a'"
        ).fetchone()
        commercial = connection.execute(
            "SELECT status FROM commercial_states WHERE business_id = 'business-a'"
        ).fetchone()
        period = connection.execute(
            "SELECT amount, currency, provider_event_id "
            "FROM subscription_billing_periods WHERE subscription_id = 'sub-a'"
        ).fetchone()

    assert subscription["status"] == "active"
    assert commercial["status"] == "active"
    assert period["amount"] == "199.00"
    assert period["currency"] == "ZAR"
    assert period["provider_event_id"] == "event-1"
    assert counts(database) == {
        "purchase_records": 1,
        "subscription_billing_periods": 1,
        "paid_business_ledger": 1,
    }


def test_duplicate_provider_event_has_no_second_settlement(setup):
    database, _, service = setup

    first = service.settle(
        subscription_id="sub-a", purchase=purchase(), recorded_at=NOW
    )
    second = service.settle(
        subscription_id="sub-a", purchase=purchase(), recorded_at=NOW
    )

    assert first.processed is True
    assert second.duplicate is True
    assert counts(database)["purchase_records"] == 1
    assert counts(database)["subscription_billing_periods"] == 1


@pytest.mark.parametrize(
    "payment",
    [
        purchase("wrong-business", business_id="another-business"),
        purchase("wrong-amount", amount=Decimal("1.00")),
        purchase("wrong-currency", currency="USD"),
    ],
)
def test_mismatched_payment_is_rejected_without_writes(setup, payment):
    database, _, service = setup

    with pytest.raises(ValueError):
        service.settle(
            subscription_id="sub-a", purchase=payment, recorded_at=NOW
        )

    assert counts(database) == {
        "purchase_records": 0,
        "subscription_billing_periods": 0,
        "paid_business_ledger": 0,
    }


def test_non_verified_purchase_object_is_rejected(setup):
    _, _, service = setup

    with pytest.raises(TypeError, match="VerifiedPurchase"):
        service.settle(
            subscription_id="sub-a",
            purchase=object(),
            recorded_at=NOW,
        )


def test_wrong_subscription_is_rejected(setup):
    database, _, service = setup

    with pytest.raises(ValueError, match="does not exist"):
        service.settle(
            subscription_id="missing",
            purchase=purchase(),
            recorded_at=NOW,
        )

    assert counts(database)["purchase_records"] == 0


def test_recurring_settlement_requires_active_matching_mandate(setup):
    database, repository, service = setup

    repository.create_recurring_mandate(
        mandate_id="mandate-a",
        subscription_id="sub-a",
        provider="test-provider",
        provider_mandate_id="external-a",
        approved_by_user_id="owner-a",
        approved_at=NOW,
        consent_version="v1",
        now=NOW,
    )

    with pytest.raises(ValueError, match="active mandate"):
        service.settle(
            subscription_id="sub-a",
            purchase=purchase(),
            recorded_at=NOW,
            mandate_id="mandate-a",
        )

    assert counts(database)["purchase_records"] == 0


def test_revoked_mandate_cannot_authorize_recurring_settlement(setup):
    database, repository, service = setup

    repository.create_recurring_mandate(
        mandate_id="mandate-a",
        subscription_id="sub-a",
        provider="test-provider",
        provider_mandate_id="external-a",
        approved_by_user_id="owner-a",
        approved_at=NOW,
        consent_version="v1",
        now=NOW,
    )

    with database.transaction() as connection:
        connection.execute(
            "UPDATE recurring_payment_mandates SET status = 'active' WHERE mandate_id = 'mandate-a'"
        )

    repository.revoke_recurring_mandate(
        mandate_id="mandate-a",
        revoked_at=NOW,
    )

    with pytest.raises(ValueError, match="active mandate"):
        service.settle(
            subscription_id="sub-a",
            purchase=purchase(),
            recorded_at=NOW,
            mandate_id="mandate-a",
        )

    assert counts(database)["purchase_records"] == 0


def test_renewal_extends_from_existing_period_end_without_double_counting(setup):
    database, _, service = setup

    first = service.settle(
        subscription_id="sub-a", purchase=purchase("event-1"), recorded_at=NOW
    )
    second_paid_at = datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc)
    second = service.settle(
        subscription_id="sub-a",
        purchase=purchase("event-2", paid_at=second_paid_at),
        recorded_at=second_paid_at,
    )

    assert second.period_start == first.period_end
    assert second.period_end == datetime(2027, 1, 12, 12, 0, tzinfo=timezone.utc)
    assert counts(database) == {
        "purchase_records": 2,
        "subscription_billing_periods": 2,
        "paid_business_ledger": 1,
    }

    with database.connection() as connection:
        launch_count = connection.execute(
            "SELECT paid_businesses FROM launch_program WHERE singleton_id = 1"
        ).fetchone()[0]
    assert launch_count == 1


def test_settlement_rejects_subscription_scheduled_for_cancellation(setup):
    database, _, service = setup

    with database.transaction() as connection:
        connection.execute(
            "UPDATE business_subscriptions SET cancel_at_period_end = 1 "
            "WHERE subscription_id = 'sub-a'"
        )

    with pytest.raises(ValueError, match="scheduled for cancellation"):
        service.settle(
            subscription_id="sub-a", purchase=purchase(), recorded_at=NOW
        )

    assert counts(database)["purchase_records"] == 0


def test_calendar_month_end_anchor_is_preserved():
    january_31 = datetime(2027, 1, 31, 12, 0, tzinfo=timezone.utc)
    february_28 = _add_calendar_months(january_31, 1, 31)
    march_31 = _add_calendar_months(february_28, 1, 31)

    assert february_28 == datetime(2027, 2, 28, 12, 0, tzinfo=timezone.utc)
    assert march_31 == datetime(2027, 3, 31, 12, 0, tzinfo=timezone.utc)


def test_naive_recorded_at_is_rejected_before_database_write(setup):
    database, _, service = setup

    with pytest.raises(ValueError, match="timezone-aware"):
        service.settle(
            subscription_id="sub-a",
            purchase=purchase(),
            recorded_at=datetime(2026, 11, 12, 12, 0),
        )

    assert counts(database)["purchase_records"] == 0


def test_repeated_month_end_renewals_preserve_original_billing_day(setup):
    database, _, service = setup
    january_31 = datetime(2027, 1, 31, 12, 0, tzinfo=timezone.utc)
    february_28 = datetime(2027, 2, 28, 12, 0, tzinfo=timezone.utc)
    march_31 = datetime(2027, 3, 31, 12, 0, tzinfo=timezone.utc)

    first = service.settle(
        subscription_id="sub-a",
        purchase=purchase("jan", paid_at=january_31),
        recorded_at=january_31,
    )
    second = service.settle(
        subscription_id="sub-a",
        purchase=purchase("feb", paid_at=february_28),
        recorded_at=february_28,
    )
    third = service.settle(
        subscription_id="sub-a",
        purchase=purchase("mar", paid_at=march_31),
        recorded_at=march_31,
    )

    assert first.period_end == february_28
    assert second.period_end == march_31
    assert third.period_end == datetime(2027, 4, 30, 12, 0, tzinfo=timezone.utc)
    assert counts(database)["subscription_billing_periods"] == 3


def test_recurring_mandate_provider_must_match_purchase_provider(setup):
    database, repository, service = setup
    repository.create_recurring_mandate(
        mandate_id="mandate-provider",
        subscription_id="sub-a",
        provider="another-provider",
        provider_mandate_id="external-provider-mandate",
        approved_by_user_id="owner-a",
        approved_at=NOW,
        consent_version="v1",
        now=NOW,
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE recurring_payment_mandates SET status = 'active' "
            "WHERE mandate_id = 'mandate-provider'"
        )

    with pytest.raises(ValueError, match="active mandate"):
        service.settle(
            subscription_id="sub-a",
            purchase=purchase("provider-mismatch"),
            recorded_at=NOW,
            mandate_id="mandate-provider",
        )

    assert counts(database)["purchase_records"] == 0


def test_failed_billing_period_insert_rolls_back_entire_settlement(setup):
    import sqlite3

    database, _, service = setup

    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_billing_period
            BEFORE INSERT ON subscription_billing_periods
            BEGIN
                SELECT RAISE(ABORT, 'forced billing period failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced billing period failure"):
        service.settle(
            subscription_id="sub-a",
            purchase=purchase("rollback-event"),
            recorded_at=NOW,
        )

    assert counts(database)["purchase_records"] == 0
    assert counts(database)["subscription_billing_periods"] == 0

    with database.transaction() as connection:
        subscription = connection.execute(
            "SELECT status FROM business_subscriptions WHERE subscription_id = ?",
            ("sub-a",),
        ).fetchone()
        commercial = connection.execute(
            "SELECT status FROM commercial_states WHERE business_id = ?",
            ("business-a",),
        ).fetchone()

    assert subscription["status"] == "pending"
    assert commercial["status"] != "active"
