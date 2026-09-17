from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.founder.analytics import FounderAnalyticsService
from app.founder.models import FounderRecord
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.trial_repository import SQLiteTrialRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)
from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.persistence.commercial_repository import SQLitePurchaseStore
from app.commercial.trial import BusinessTrial

from tests.test_founder_operations import (
    NOW,
    add_business,
    add_purchase,
    add_trial,
    make_database,
)
from tests.test_web_application import (
    login,
    make_app,
    signup,
)


def make_founder(db, user_id: str, active: bool = True) -> None:
    SQLiteFounderRepository(db).save(
        FounderRecord(
            user_id=user_id,
            active=active,
        )
    )


def test_founder_analytics_reports_authoritative_business_and_commercial_counts(
    tmp_path,
):
    db = make_database(tmp_path)

    add_business(
        db,
        business_id="active-business",
        status=CommercialStatus.ACTIVE,
    )
    add_business(
        db,
        business_id="trial-business",
        status=CommercialStatus.TRIAL,
    )
    add_business(
        db,
        business_id="expired-business",
        status=CommercialStatus.EXPIRED,
    )
    add_business(
        db,
        business_id="suspended-business",
        status=CommercialStatus.SUSPENDED,
    )

    analytics = FounderAnalyticsService(db).summary()

    assert analytics.businesses.value == 4
    assert analytics.active_businesses.value == 1
    assert analytics.trial_businesses.value == 1
    assert analytics.expired_businesses.value == 1
    assert analytics.suspended_businesses.value == 1

    for metric in (
        analytics.businesses,
        analytics.active_businesses,
        analytics.trial_businesses,
        analytics.expired_businesses,
        analytics.suspended_businesses,
    ):
        assert metric.status == "available"
        assert metric.source == "database"


def test_founder_analytics_reports_trials_conversion_and_exact_revenue(
    tmp_path,
):
    db = make_database(tmp_path)

    add_business(db, business_id="trial-paid")
    add_business(db, business_id="trial-only")
    add_business(db, business_id="paid-without-trial")

    add_trial(db, "trial-paid", NOW)
    add_trial(db, "trial-only", NOW)

    add_purchase(
        db,
        business_id="trial-paid",
        event_id="purchase-1",
        amount="100.10",
    )
    add_purchase(
        db,
        business_id="trial-paid",
        event_id="purchase-2",
        amount="0.20",
    )
    add_purchase(
        db,
        business_id="paid-without-trial",
        event_id="purchase-3",
        amount="49.70",
    )

    analytics = FounderAnalyticsService(db).summary()

    assert analytics.trials_started.value == 2
    assert analytics.trial_conversions.value == 1
    assert analytics.trial_conversion_rate.value == "50.00%"
    assert analytics.verified_purchases.value == 3
    assert analytics.revenue.value == "ZAR 150.00"


def test_founder_analytics_does_not_invent_uninstrumented_metrics(tmp_path):
    db = make_database(tmp_path)

    add_business(db)

    analytics = FounderAnalyticsService(db).summary()

    for metric in (
        analytics.execution_volume,
        analytics.integration_health,
        analytics.website_visitors,
        analytics.website_page_views,
    ):
        assert metric.value is None
        assert metric.status == "not_instrumented"


def test_founder_analytics_reports_recorded_event_outcomes_and_channels(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db)

    repository = SQLitePlatformEventRepository(db)

    events = (
        (
            "event-success-web",
            PlatformEventChannel.WEB,
            PlatformEventOutcome.SUCCESS,
        ),
        (
            "event-success-whatsapp",
            PlatformEventChannel.WHATSAPP,
            PlatformEventOutcome.SUCCESS,
        ),
        (
            "event-failure-web",
            PlatformEventChannel.WEB,
            PlatformEventOutcome.FAILURE,
        ),
        (
            "event-denied-api",
            PlatformEventChannel.API,
            PlatformEventOutcome.DENIED,
        ),
        (
            "event-error-voice",
            PlatformEventChannel.VOICE,
            PlatformEventOutcome.ERROR,
        ),
    )

    for index, (event_id, channel, outcome) in enumerate(events):
        repository.append(
            PlatformEvent(
                event_id=event_id,
                occurred_at=NOW + timedelta(minutes=index),
                event_type="test.operation",
                business_id="business-1",
                user_id=None,
                channel=channel,
                actor_type=PlatformEventActorType.SYSTEM,
                action="test.action",
                outcome=outcome,
                correlation_id=f"correlation-{event_id}",
                metadata={"test": True},
            )
        )

    analytics = FounderAnalyticsService(db).summary()

    assert analytics.recorded_events.value == 5
    assert analytics.successful_events.value == 2
    assert analytics.failed_events.value == 1
    assert analytics.denied_events.value == 1
    assert analytics.error_events.value == 1

    assert analytics.channel_events == {
        "api": 1,
        "voice": 1,
        "web": 2,
        "whatsapp": 1,
    }


def test_founder_analytics_empty_database_is_real_zero_not_fake_activity(
    tmp_path,
):
    db = make_database(tmp_path)

    analytics = FounderAnalyticsService(db).summary()

    assert analytics.businesses.value == 0
    assert analytics.trials_started.value == 0
    assert analytics.trial_conversions.value == 0
    assert analytics.trial_conversion_rate.value == "0.00%"
    assert analytics.verified_purchases.value == 0
    assert analytics.revenue.value == "0.00"
    assert analytics.recorded_events.value == 0
    assert analytics.channel_events == {}


def test_founder_analytics_is_read_only(tmp_path):
    db = make_database(tmp_path)

    add_business(db)
    add_trial(db, "business-1", NOW)
    add_purchase(
        db,
        business_id="business-1",
        event_id="purchase-1",
        amount="25.00",
    )

    before = FounderAnalyticsService(db).summary()
    FounderAnalyticsService(db).summary()
    after = FounderAnalyticsService(db).summary()

    assert before == after
    assert after.businesses.value == 1
    assert after.trials_started.value == 1
    assert after.verified_purchases.value == 1


def test_founder_analytics_rejects_invalid_persisted_purchase_amount(tmp_path):
    db = make_database(tmp_path)
    add_business(db)

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO purchase_records(
                provider,
                provider_event_id,
                business_id,
                amount,
                currency,
                paid_at,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-provider",
                "invalid-amount",
                "business-1",
                "not-a-number",
                "ZAR",
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )

    try:
        FounderAnalyticsService(db).summary()
    except RuntimeError as exc:
        assert str(exc) == "Invalid persisted purchase amount."
    else:
        raise AssertionError("Expected invalid persisted purchase data to fail.")


def test_founder_analytics_does_not_count_pre_trial_purchase_as_conversion(
    tmp_path,
):
    db = make_database(tmp_path)

    add_business(db, business_id="business-1")

    trial_started = NOW
    purchase_before_trial = NOW - timedelta(days=2)

    add_trial(db, "business-1", trial_started)
    add_purchase(
        db,
        business_id="business-1",
        event_id="purchase-before-trial",
        amount="100.00",
        paid_at=purchase_before_trial,
    )

    analytics = FounderAnalyticsService(db).summary()

    assert analytics.trials_started.value == 1
    assert analytics.trial_conversions.value == 0
    assert analytics.trial_conversion_rate.value == "0.00%"


def test_founder_analytics_api_requires_founder_authorization(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    response = client.get("/api/founder/analytics")

    assert response.status_code == 403


def test_founder_analytics_api_requires_authentication(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    response = client.get("/api/founder/analytics")

    assert response.status_code in {401, 403}


def test_founder_analytics_api_returns_authoritative_metrics(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None

    make_founder(db, user.user_id)


    business_id = client.get("/api/me").get_json()["business_id"]
    SQLiteCommercialStateRepository(db).save(
        BusinessCommercialState(
            business_id=business_id,
            status=CommercialStatus.ACTIVE,
        )
    )

    response = client.get("/api/founder/analytics")

    assert response.status_code == 200

    data = response.get_json()

    assert data["businesses"]["value"] == 1
    assert data["businesses"]["status"] == "available"
    assert data["businesses"]["source"] == "database"

    assert data["active_businesses"]["value"] == 1
    assert data["trials_started"]["value"] == 1
    assert data["trial_conversions"]["value"] == 0
    assert data["revenue"]["value"] == "0.00"


def test_founder_analytics_api_exposes_uninstrumented_metrics_explicitly(
    tmp_path,
):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    business_id = client.get("/api/me").get_json()["business_id"]
    SQLiteCommercialStateRepository(db).save(
        BusinessCommercialState(
            business_id=business_id,
            status=CommercialStatus.ACTIVE,
        )
    )

    response = client.get("/api/founder/analytics")

    assert response.status_code == 200

    data = response.get_json()

    for metric_name in (
        "execution_volume",
        "integration_health",
        "website_visitors",
        "website_page_views",
    ):
        metric = data[metric_name]
        assert metric["value"] is None
        assert metric["status"] == "not_instrumented"


def test_founder_analytics_api_is_read_only(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    with db.connection() as connection:
        before_counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "businesses",
                "business_trials",
                "commercial_states",
                "purchase_records",
                "platform_events",
            )
        }

    response = client.get("/api/founder/analytics")

    assert response.status_code == 200

    with db.connection() as connection:
        after_counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in before_counts
        }

    assert after_counts == before_counts


def test_founder_analytics_api_rejects_mutation_methods(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    assert client.post("/api/founder/analytics").status_code == 405
    assert client.put("/api/founder/analytics").status_code == 405
    assert client.delete("/api/founder/analytics").status_code == 405
