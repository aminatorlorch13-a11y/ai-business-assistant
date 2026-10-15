from datetime import datetime, timezone

import pytest

from app.assistant.conversation import ConversationRole
from app.identity.models import BusinessMembership, User, UserRole
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.web_conversation import SQLiteWebConversationRepository


def make_repository(tmp_path):
    database = SQLiteDatabase(tmp_path / "web-conversation.sqlite3")
    database.initialize()

    businesses = SQLiteBusinessRepository(database)
    users = SQLiteUserRepository(database)
    memberships = SQLiteMembershipRepository(database)

    businesses.save(
        Business(
            business_id="business-1",
            name="Business One",
            owner_name="Owner One",
            assistant_name="Assistant One",
            assistant_voice="female",
        )
    )
    users.save(
        User(
            user_id="user-1",
            display_name="User One",
            email="user1@example.com",
        )
    )
    users.save(
        User(
            user_id="user-2",
            display_name="User Two",
            email="user2@example.com",
        )
    )
    memberships.save(
        BusinessMembership(
            user_id="user-1",
            business_id="business-1",
            role=UserRole.OWNER,
        )
    )

    return database, SQLiteWebConversationRepository(database)


def append(repository, number):
    return repository.append_exchange(
        user_id="user-1",
        business_id="business-1",
        user_content=f"user-{number}",
        assistant_content=f"assistant-{number}",
        created_at=datetime.now(timezone.utc),
    )


def test_fresh_database_has_web_conversation_schema(tmp_path):
    database, _ = make_repository(tmp_path)

    assert SCHEMA_VERSION == 14

    with database.connection() as connection:
        version = connection.execute(
            """
            SELECT value FROM persistence_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()
        table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'web_conversation_turns'
            """
        ).fetchone()
        index = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_web_conversation_business_user'
            """
        ).fetchone()

    assert int(version["value"]) == SCHEMA_VERSION
    assert table is not None
    assert index is not None


def test_exchange_round_trips_in_order(tmp_path):
    _, repository = make_repository(tmp_path)

    append(repository, 1)
    history = append(repository, 2)

    assert [turn.content for turn in history.turns] == [
        "user-1",
        "assistant-1",
        "user-2",
        "assistant-2",
    ]
    assert history.turns[0].role is ConversationRole.USER
    assert history.turns[1].role is ConversationRole.ASSISTANT


def test_history_loads_all_stored_exchanges_by_default(tmp_path):
    _, repository = make_repository(tmp_path)

    for number in range(128):
        append(repository, number)

    history = repository.load_history(
        user_id="user-1",
        business_id="business-1",
    )
    expected = [
        item
        for number in range(128)
        for item in (f"user-{number}", f"assistant-{number}")
    ]
    assert [turn.content for turn in history.turns] == expected
    assert len(history.turns) == 256


def test_nonmember_cannot_read_or_write_history(tmp_path):
    _, repository = make_repository(tmp_path)

    with pytest.raises(PermissionError):
        repository.load_history(
            user_id="user-2",
            business_id="business-1",
        )

    with pytest.raises(PermissionError):
        repository.append_exchange(
            user_id="user-2",
            business_id="business-1",
            user_content="unauthorized",
            assistant_content="must not be stored",
            created_at=datetime.now(timezone.utc),
        )


def test_invalid_exchange_does_not_write_partial_history(tmp_path):
    database, repository = make_repository(tmp_path)

    with pytest.raises(ValueError):
        repository.append_exchange(
            user_id="user-1",
            business_id="business-1",
            user_content=" ",
            assistant_content="hello back",
            created_at=datetime.now(timezone.utc),
        )

    with database.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM web_conversation_turns"
        ).fetchone()[0]

    assert count == 0
