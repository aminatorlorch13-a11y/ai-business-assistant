from datetime import datetime, timezone

import pytest

from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_db(tmp_path):
    db = SQLiteDatabase(tmp_path / "platform-events.sqlite3")
    db.initialize()
    return db


def make_business(business_id):
    return Business(
        business_id,
        business_id,
        "Owner",
        "Configured Test Assistant",
        "female",
    )


def make_event(
    *,
    event_id="event-1",
    business_id=None,
    user_id=None,
    correlation_id="corr-1",
    metadata=None,
):
    return PlatformEvent(
        event_id=event_id,
        occurred_at=NOW,
        event_type="assistant.action",
        business_id=business_id,
        user_id=user_id,
        channel=PlatformEventChannel.WEB,
        actor_type=PlatformEventActorType.USER,
        action="send_message",
        outcome=PlatformEventOutcome.SUCCESS,
        correlation_id=correlation_id,
        metadata=metadata or {"duration_ms": 100},
    )


def test_database_schema_matches_current_version(tmp_path):
    db = make_db(tmp_path)

    with db.connection() as connection:
        version = connection.execute(
            """
            SELECT value
            FROM persistence_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()[0]

    assert int(version) == SCHEMA_VERSION


def test_platform_events_table_exists(tmp_path):
    db = make_db(tmp_path)

    with db.connection() as connection:
        row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'platform_events'
            """
        ).fetchone()

    assert row is not None


def test_repository_appends_and_reads_event(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    event = make_event()

    repo.append(event)
    loaded = repo.get(event.event_id)

    assert loaded == event


def test_repository_preserves_enum_types_when_reading(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    event = make_event()
    repo.append(event)

    loaded = repo.get(event.event_id)

    assert loaded.channel is PlatformEventChannel.WEB
    assert loaded.actor_type is PlatformEventActorType.USER
    assert loaded.outcome is PlatformEventOutcome.SUCCESS


def test_duplicate_event_id_is_rejected(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    event = make_event()

    repo.append(event)

    with pytest.raises(ValueError):
        repo.append(event)


def test_missing_business_reference_is_rejected(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    event = make_event(business_id="missing-business")

    with pytest.raises(Exception):
        repo.append(event)


def test_missing_user_reference_is_rejected(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    event = make_event(user_id="missing-user")

    with pytest.raises(Exception):
        repo.append(event)


def test_business_reference_can_be_persisted(tmp_path):
    db = make_db(tmp_path)

    SQLiteBusinessRepository(db).save(
        make_business("business-1")
    )

    repo = SQLitePlatformEventRepository(db)
    event = make_event(business_id="business-1")

    repo.append(event)

    assert repo.get(event.event_id) == event


def test_list_for_business_is_scoped(tmp_path):
    db = make_db(tmp_path)
    businesses = SQLiteBusinessRepository(db)

    businesses.save(make_business("business-a"))
    businesses.save(make_business("business-b"))

    repo = SQLitePlatformEventRepository(db)

    repo.append(
        make_event(
            event_id="event-a",
            business_id="business-a",
        )
    )
    repo.append(
        make_event(
            event_id="event-b",
            business_id="business-b",
        )
    )

    events = repo.list_for_business("business-a")

    assert [event.event_id for event in events] == ["event-a"]


def test_list_for_correlation_returns_matching_events(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    repo.append(
        make_event(
            event_id="event-1",
            correlation_id="corr-1",
        )
    )
    repo.append(
        make_event(
            event_id="event-2",
            correlation_id="corr-1",
        )
    )
    repo.append(
        make_event(
            event_id="event-3",
            correlation_id="corr-2",
        )
    )

    events = repo.list_for_correlation("corr-1")

    assert [event.event_id for event in events] == [
        "event-2",
        "event-1",
    ]


def test_list_recent_returns_newest_events_first(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    repo.append(make_event(event_id="event-1"))
    repo.append(make_event(event_id="event-2"))

    events = repo.list_recent()

    assert [event.event_id for event in events[:2]] == [
        "event-2",
        "event-1",
    ]


def test_platform_events_reject_direct_update(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    repo.append(make_event())

    with pytest.raises(Exception):
        with db.connection() as connection:
            connection.execute(
                """
                UPDATE platform_events
                SET action = 'tampered'
                WHERE event_id = ?
                """,
                ("event-1",),
            )


def test_platform_events_reject_direct_delete(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    repo.append(make_event())

    with pytest.raises(Exception):
        with db.connection() as connection:
            connection.execute(
                """
                DELETE FROM platform_events
                WHERE event_id = ?
                """,
                ("event-1",),
            )


def test_repository_does_not_expose_mutation_methods():
    assert not hasattr(
        SQLitePlatformEventRepository,
        "update",
    )
    assert not hasattr(
        SQLitePlatformEventRepository,
        "delete",
    )


def test_business_deletion_preserves_platform_event(tmp_path):
    db = make_db(tmp_path)
    businesses = SQLiteBusinessRepository(db)

    businesses.save(make_business("business-1"))

    repo = SQLitePlatformEventRepository(db)
    repo.append(
        make_event(
            business_id="business-1",
        )
    )

    with db.transaction() as connection:
        connection.execute(
            "DELETE FROM businesses WHERE business_id = ?",
            ("business-1",),
        )

    loaded = repo.get("event-1")

    assert loaded is not None
    assert loaded.business_id == "business-1"


def test_recent_limit_is_enforced(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    with pytest.raises(ValueError):
        repo.list_recent(limit=501)


def test_business_limit_is_enforced(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    with pytest.raises(ValueError):
        repo.list_for_business("business-1", limit=501)


def test_correlation_limit_is_enforced(tmp_path):
    db = make_db(tmp_path)
    repo = SQLitePlatformEventRepository(db)

    with pytest.raises(ValueError):
        repo.list_for_correlation("corr-1", limit=501)
