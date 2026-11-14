from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.persistence.database import SQLiteDatabase
from app.persistence.subscription_repository import SQLiteSubscriptionRepository


NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path):
    database = SQLiteDatabase(tmp_path / "subscriptions.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        for business_id in ("business-a", "business-b"):
            connection.execute(
                """
                INSERT INTO businesses(
                    business_id, name, owner_name, assistant_name, assistant_voice
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (business_id, business_id, "Owner", "Assistant", "male"),
            )
            connection.execute(
                "INSERT INTO commercial_states(business_id, status) VALUES (?, ?)",
                (business_id, "trial"),
            )

        connection.execute(
            "INSERT INTO users(user_id, display_name, email) VALUES (?, ?, ?)",
            ("owner-a", "Owner A", "owner-a@example.test"),
        )
        connection.execute(
            "INSERT INTO users(user_id, display_name, email) VALUES (?, ?, ?)",
            ("owner-b", "Owner B", "owner-b@example.test"),
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
    return database, repository


def create_subscription(repository, subscription_id="sub-a", business_id="business-a"):
    repository.create_subscription(
        subscription_id=subscription_id,
        business_id=business_id,
        plan_id="monthly",
        now=NOW,
    )


def test_create_plan_and_subscription(setup):
    _, repository = setup
    create_subscription(repository)

    subscription = repository.get_subscription("sub-a")
    assert subscription["business_id"] == "business-a"
    assert subscription["plan_id"] == "monthly"
    assert subscription["status"] == "pending"
    assert subscription["current_period_start"] is None
    assert subscription["current_period_end"] is None


def test_inactive_or_missing_plan_cannot_create_subscription(setup):
    _, repository = setup

    with pytest.raises(ValueError, match="active subscription plan"):
        repository.create_subscription(
            subscription_id="missing-plan",
            business_id="business-a",
            plan_id="does-not-exist",
            now=NOW,
        )

    with repository._database.transaction() as connection:
        connection.execute(
            "UPDATE subscription_plans SET active = 0 WHERE plan_id = 'monthly'"
        )

    with pytest.raises(ValueError, match="active subscription plan"):
        create_subscription(repository)


def test_only_one_open_subscription_per_business(setup):
    _, repository = setup
    create_subscription(repository)

    with pytest.raises(ValueError, match="Subscription could not be created"):
        create_subscription(repository, subscription_id="sub-duplicate")


def test_recurring_mandate_starts_pending_and_can_be_revoked_once(setup):
    _, repository = setup
    create_subscription(repository)

    repository.create_recurring_mandate(
        mandate_id="mandate-a",
        subscription_id="sub-a",
        provider="provider-a",
        provider_mandate_id="external-mandate-a",
        approved_by_user_id="owner-a",
        approved_at=NOW,
        consent_version="v1",
        now=NOW,
    )

    with repository._database.connection() as connection:
        mandate = connection.execute(
            "SELECT status, approved_by_user_id, consent_version "
            "FROM recurring_payment_mandates WHERE mandate_id = ?",
            ("mandate-a",),
        ).fetchone()

    assert mandate["status"] == "pending"
    assert mandate["approved_by_user_id"] == "owner-a"
    assert mandate["consent_version"] == "v1"
    assert repository.revoke_recurring_mandate(
        mandate_id="mandate-a", revoked_at=NOW
    ) is True
    assert repository.revoke_recurring_mandate(
        mandate_id="mandate-a", revoked_at=NOW
    ) is False


def test_manual_payment_stays_pending_and_does_not_activate_access(setup):
    database, repository = setup
    create_subscription(repository)

    repository.submit_manual_payment(
        request_id="request-a",
        business_id="business-a",
        subscription_id="sub-a",
        submitted_by_user_id="owner-a",
        amount=Decimal("199.00"),
        currency="ZAR",
        payment_reference="EFT-REFERENCE-123",
        evidence_reference=None,
        submitted_at=NOW,
    )

    with database.connection() as connection:
        request = connection.execute(
            "SELECT status FROM manual_payment_requests WHERE request_id = ?",
            ("request-a",),
        ).fetchone()
        commercial = connection.execute(
            "SELECT status FROM commercial_states WHERE business_id = ?",
            ("business-a",),
        ).fetchone()
        subscription = connection.execute(
            "SELECT status FROM business_subscriptions WHERE subscription_id = ?",
            ("sub-a",),
        ).fetchone()

    assert request["status"] == "pending"
    assert commercial["status"] == "trial"
    assert subscription["status"] == "pending"


def test_manual_payment_review_does_not_settle_subscription(setup):
    database, repository = setup
    create_subscription(repository)

    repository.submit_manual_payment(
        request_id="request-review",
        business_id="business-a",
        subscription_id="sub-a",
        submitted_by_user_id="owner-a",
        amount=Decimal("199.00"),
        currency="ZAR",
        payment_reference="EFT-REVIEW-123",
        evidence_reference=None,
        submitted_at=NOW,
    )

    assert repository.review_manual_payment(
        request_id="request-review",
        reviewer_user_id="owner-b",
        decision="verified",
        reason="Reviewed manually; settlement still requires verified purchase.",
        reviewed_at=NOW,
    ) is True

    assert repository.review_manual_payment(
        request_id="request-review",
        reviewer_user_id="owner-b",
        decision="verified",
        reason="Second review must not change the result.",
        reviewed_at=NOW,
    ) is False

    with database.connection() as connection:
        request = connection.execute(
            "SELECT status FROM manual_payment_requests WHERE request_id = ?",
            ("request-review",),
        ).fetchone()
        subscription = connection.execute(
            "SELECT status FROM business_subscriptions WHERE subscription_id = ?",
            ("sub-a",),
        ).fetchone()
        commercial = connection.execute(
            "SELECT status FROM commercial_states WHERE business_id = ?",
            ("business-a",),
        ).fetchone()
        purchase_count = connection.execute(
            "SELECT COUNT(*) FROM purchase_records"
        ).fetchone()[0]
        period_count = connection.execute(
            "SELECT COUNT(*) FROM subscription_billing_periods"
        ).fetchone()[0]

    assert request["status"] == "verified"
    assert subscription["status"] == "pending"
    assert commercial["status"] == "trial"
    assert purchase_count == 0
    assert period_count == 0


def test_manual_payment_cannot_be_submitted_for_another_business_subscription(setup):
    _, repository = setup
    create_subscription(repository)

    with pytest.raises(ValueError, match="does not belong"):
        repository.submit_manual_payment(
            request_id="cross-tenant",
            business_id="business-b",
            subscription_id="sub-a",
            submitted_by_user_id="owner-b",
            amount=Decimal("199.00"),
            currency="ZAR",
            payment_reference="CROSS-TENANT",
            evidence_reference=None,
            submitted_at=NOW,
        )


def test_pending_manual_payments_are_ordered_and_limited(setup):
    _, repository = setup
    create_subscription(repository)

    for request_id in ("request-1", "request-2"):
        repository.submit_manual_payment(
            request_id=request_id,
            business_id="business-a",
            subscription_id="sub-a",
            submitted_by_user_id="owner-a",
            amount=Decimal("199.00"),
            currency="ZAR",
            payment_reference=f"REF-{request_id}",
            evidence_reference=None,
            submitted_at=NOW,
        )

    assert [row["request_id"] for row in repository.list_pending_manual_payments()] == [
        "request-1",
        "request-2",
    ]

    with pytest.raises(ValueError, match="must not exceed 500"):
        repository.list_pending_manual_payments(limit=501)


@pytest.mark.parametrize(
    "amount",
    [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_plan_rejects_invalid_amounts(setup, amount):
    _, repository = setup

    with pytest.raises(ValueError):
        repository.create_plan(
            plan_id="invalid",
            name="Invalid",
            amount=amount,
            currency="ZAR",
            interval_months=1,
            now=NOW,
        )


def test_plan_rejects_invalid_currency_and_interval(setup):
    _, repository = setup

    with pytest.raises(ValueError, match="currency"):
        repository.create_plan(
            plan_id="bad-currency",
            name="Bad currency",
            amount=Decimal("10.00"),
            currency="zar",
            interval_months=1,
            now=NOW,
        )

    with pytest.raises(ValueError, match="interval_months"):
        repository.create_plan(
            plan_id="bad-interval",
            name="Bad interval",
            amount=Decimal("10.00"),
            currency="ZAR",
            interval_months=0,
            now=NOW,
        )


def test_repository_rejects_naive_datetimes(setup):
    _, repository = setup

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.create_plan(
            plan_id="naive",
            name="Naive",
            amount=Decimal("10.00"),
            currency="ZAR",
            interval_months=1,
            now=datetime(2026, 11, 12, 12, 0),
        )

def test_scheduled_cancellation_preserves_paid_period_and_business_access(setup):
    database, repository = setup
    create_subscription(repository)
    paid_end = datetime(2026, 12, 12, 12, 0, tzinfo=timezone.utc)

    with database.transaction() as connection:
        connection.execute(
            """UPDATE business_subscriptions
               SET status = 'active', current_period_start = ?, current_period_end = ?
               WHERE subscription_id = 'sub-a'""",
            (NOW.isoformat(), paid_end.isoformat()),
        )

    repository.create_recurring_mandate(
        mandate_id="mandate-scheduled", subscription_id="sub-a",
        provider="provider-a", provider_mandate_id="external-scheduled",
        approved_by_user_id="owner-a", approved_at=NOW,
        consent_version="v1", now=NOW,
    )

    assert repository.cancel_subscription(
        subscription_id="sub-a", cancelled_at=NOW, at_period_end=True
    ) is True
    assert repository.cancel_subscription(
        subscription_id="sub-a", cancelled_at=NOW, at_period_end=True
    ) is False

    with database.connection() as connection:
        subscription = connection.execute(
            """SELECT status, current_period_end, cancel_at_period_end, cancelled_at
               FROM business_subscriptions WHERE subscription_id = 'sub-a'"""
        ).fetchone()
        mandate = connection.execute(
            "SELECT status FROM recurring_payment_mandates WHERE mandate_id = ?",
            ("mandate-scheduled",),
        ).fetchone()
        commercial = connection.execute(
            "SELECT status FROM commercial_states WHERE business_id = 'business-a'"
        ).fetchone()

    assert subscription["status"] == "active"
    assert subscription["current_period_end"] == paid_end.isoformat()
    assert subscription["cancel_at_period_end"] == 1
    assert subscription["cancelled_at"] is None
    assert mandate["status"] == "revoked"
    assert commercial["status"] == "trial"


def test_immediate_cancellation_cancels_pending_requests_and_preserves_trial(setup):
    database, repository = setup
    create_subscription(repository)
    repository.submit_manual_payment(
        request_id="request-cancel", business_id="business-a",
        subscription_id="sub-a", submitted_by_user_id="owner-a",
        amount=Decimal("199.00"), currency="ZAR",
        payment_reference="EFT-CANCEL-123", evidence_reference=None,
        submitted_at=NOW,
    )
    repository.create_recurring_mandate(
        mandate_id="mandate-immediate", subscription_id="sub-a",
        provider="provider-a", provider_mandate_id="external-immediate",
        approved_by_user_id="owner-a", approved_at=NOW,
        consent_version="v1", now=NOW,
    )

    assert repository.cancel_subscription(
        subscription_id="sub-a", cancelled_at=NOW, at_period_end=False
    ) is True
    assert repository.cancel_subscription(
        subscription_id="sub-a", cancelled_at=NOW, at_period_end=False
    ) is False

    with database.connection() as connection:
        subscription = connection.execute(
            """SELECT status, cancel_at_period_end, cancelled_at
               FROM business_subscriptions WHERE subscription_id = 'sub-a'"""
        ).fetchone()
        request = connection.execute(
            "SELECT status FROM manual_payment_requests WHERE request_id = ?",
            ("request-cancel",),
        ).fetchone()
        mandate = connection.execute(
            "SELECT status FROM recurring_payment_mandates WHERE mandate_id = ?",
            ("mandate-immediate",),
        ).fetchone()
        commercial = connection.execute(
            "SELECT status FROM commercial_states WHERE business_id = 'business-a'"
        ).fetchone()

    assert subscription["status"] == "cancelled"
    assert subscription["cancel_at_period_end"] == 0
    assert subscription["cancelled_at"] == NOW.isoformat()
    assert request["status"] == "cancelled"
    assert mandate["status"] == "revoked"
    assert commercial["status"] == "trial"


def test_immediate_cancellation_preserves_existing_active_business_access(setup):
    database, repository = setup
    create_subscription(repository)

    with database.transaction() as connection:
        connection.execute(
            "UPDATE commercial_states SET status = 'active' WHERE business_id = ?",
            ("business-a",),
        )

    assert repository.cancel_subscription(
        subscription_id="sub-a", cancelled_at=NOW, at_period_end=False
    ) is True

    with database.connection() as connection:
        commercial = connection.execute(
            "SELECT status FROM commercial_states WHERE business_id = ?",
            ("business-a",),
        ).fetchone()

    assert commercial["status"] == "active"

