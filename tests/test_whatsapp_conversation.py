from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.identity.models import BusinessMembership, User, UserRole
from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.persistence.whatsapp_conversation import (
    SQLiteWhatsAppConversationRepository,
)
from app.whatsapp.models import WhatsAppBinding
from app.whatsapp.security import hash_sender_id


SENDER_SECRET = "conversation-test-secret"


def make_database(path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(path)
    database.initialize()

    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id,
                name,
                owner_name,
                assistant_name,
                assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "business-1",
                "Business One",
                "Owner One",
                "Assistant One",
                "calm",
            ),
        )
        connection.execute(
            """
            INSERT INTO businesses(
                business_id,
                name,
                owner_name,
                assistant_name,
                assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "business-2",
                "Business Two",
                "Owner Two",
                "Assistant Two",
                "calm",
            ),
        )

        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            ("user-1", "User One", "user1@example.com"),
        )
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            ("user-2", "User Two", "user2@example.com"),
        )

    membership_repository = SQLiteMembershipRepository(database)

    membership_repository.save(
        BusinessMembership(
            user_id="user-1",
            business_id="business-1",
            role=UserRole.OWNER,
        )
    )

    membership_repository.save(
        BusinessMembership(
            user_id="user-2",
            business_id="business-1",
            role=UserRole.MEMBER,
        )
    )

    membership_repository.save(
        BusinessMembership(
            user_id="user-2",
            business_id="business-2",
            role=UserRole.OWNER,
        )
    )

    return database


def add_binding(
    database: SQLiteDatabase,
    *,
    binding_id: str,
    provider: str,
    provider_account_id: str,
    sender_id: str,
    user_id: str,
    business_id: str,
    role: UserRole = UserRole.MEMBER,
    active: bool = True,
) -> WhatsAppBinding:
    binding = WhatsAppBinding(
        binding_id=binding_id,
        provider=provider,
        provider_account_id=provider_account_id,
        sender_id_hash=hash_sender_id(sender_id, SENDER_SECRET),
        user_id=user_id,
        business_id=business_id,
        role=role,
        active=active,
    )

    SQLiteWhatsAppRepository(database).save_binding(binding)
    return binding


def repository(database: SQLiteDatabase) -> SQLiteWhatsAppConversationRepository:
    return SQLiteWhatsAppConversationRepository(database)


def now() -> datetime:
    return datetime.now(timezone.utc)


def test_append_and_reload_reconstructs_phase_b_history(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    repo.append_exchange(
        binding_id="binding-1",
        business_id="business-1",
        user_content="What are your opening hours?",
        assistant_content="We are open from 08:00 to 17:00.",
        created_at=now(),
    )

    history = repo.load_history(
        binding_id="binding-1",
        business_id="business-1",
    )

    assert len(history.turns) == 2
    assert history.turns[0].content == "What are your opening hours?"
    assert history.turns[1].content == "We are open from 08:00 to 17:00."


def test_same_business_bindings_have_isolated_histories(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-user-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    add_binding(
        database,
        binding_id="binding-user-2",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27222222222",
        user_id="user-2",
        business_id="business-1",
    )

    repo = repository(database)

    repo.append_exchange(
        binding_id="binding-user-1",
        business_id="business-1",
        user_content="Private customer question",
        assistant_content="Private customer answer",
        created_at=now(),
    )

    history = repo.load_history(
        binding_id="binding-user-2",
        business_id="business-1",
    )

    assert history.turns == ()


def test_cross_business_history_access_is_rejected(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-business-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    with pytest.raises(PermissionError):
        repo.load_history(
            binding_id="binding-business-1",
            business_id="business-2",
        )


def test_cross_business_append_is_rejected(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-business-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    with pytest.raises(PermissionError):
        repo.append_exchange(
            binding_id="binding-business-1",
            business_id="business-2",
            user_content="Forged message",
            assistant_content="Forged response",
            created_at=now(),
        )


def test_unknown_binding_cannot_access_history(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    repo = repository(database)

    with pytest.raises(PermissionError):
        repo.load_history(
            binding_id="forged-binding",
            business_id="business-1",
        )


def test_inactive_binding_cannot_access_history(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="inactive-binding",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
        active=False,
    )

    repo = repository(database)

    with pytest.raises(PermissionError):
        repo.load_history(
            binding_id="inactive-binding",
            business_id="business-1",
        )


def test_inactive_binding_cannot_append_history(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="inactive-binding",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
        active=False,
    )

    repo = repository(database)

    with pytest.raises(PermissionError):
        repo.append_exchange(
            binding_id="inactive-binding",
            business_id="business-1",
            user_content="Should not persist",
            assistant_content="Should not persist",
            created_at=now(),
        )


def test_history_retains_all_turns_by_default(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    for index in range(15):
        repo.append_exchange(
            binding_id="binding-1",
            business_id="business-1",
            user_content=f"user-{index}",
            assistant_content=f"assistant-{index}",
            created_at=now(),
        )

    history = repo.load_history(
        binding_id="binding-1",
        business_id="business-1",
    )

    assert len(history.turns) == 30

    assert history.turns[0].content == "user-0"
    assert history.turns[-1].content == "assistant-14"

    for index in range(0, len(history.turns), 2):
        assert history.turns[index].content.startswith("user-")
        assert history.turns[index + 1].content.startswith("assistant-")


def test_odd_history_limit_is_rejected(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    with pytest.raises(ValueError):
        repo.load_history(
            binding_id="binding-1",
            business_id="business-1",
            max_turns=3,
        )

    with pytest.raises(ValueError):
        repo.append_exchange(
            binding_id="binding-1",
            business_id="business-1",
            user_content="hello",
            assistant_content="hi",
            created_at=now(),
            max_turns=3,
        )


def test_failed_exchange_rolls_back_both_turns(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    with pytest.raises(Exception):
        repo.append_exchange(
            binding_id="binding-1",
            business_id="business-1",
            user_content="valid user content",
            assistant_content="valid assistant content",
            created_at=now(),
            max_turns=0,
        )

    history = repo.load_history(
        binding_id="binding-1",
        business_id="business-1",
    )

    assert history.turns == ()


def test_provider_account_collisions_do_not_merge_bindings(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-meta-account-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    add_binding(
        database,
        binding_id="binding-meta-account-2",
        provider="meta",
        provider_account_id="account-2",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    repo.append_exchange(
        binding_id="binding-meta-account-1",
        business_id="business-1",
        user_content="Account one secret",
        assistant_content="Account one answer",
        created_at=now(),
    )

    history = repo.load_history(
        binding_id="binding-meta-account-2",
        business_id="business-1",
    )

    assert history.turns == ()


def test_different_providers_do_not_merge_bindings(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-meta",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    add_binding(
        database,
        binding_id="binding-other",
        provider="other-provider",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    repo.append_exchange(
        binding_id="binding-meta",
        business_id="business-1",
        user_content="Meta private context",
        assistant_content="Meta private answer",
        created_at=now(),
    )

    history = repo.load_history(
        binding_id="binding-other",
        business_id="business-1",
    )

    assert history.turns == ()


def test_foreign_key_cascade_removes_binding_history(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    repo.append_exchange(
        binding_id="binding-1",
        business_id="business-1",
        user_content="Will be deleted",
        assistant_content="Will also be deleted",
        created_at=now(),
    )

    with database.connection() as connection:
        connection.execute(
            "DELETE FROM whatsapp_bindings WHERE binding_id = ?",
            ("binding-1",),
        )

        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM whatsapp_conversation_turns
            WHERE binding_id = ?
            """,
            ("binding-1",),
        ).fetchone()[0]

    assert count == 0


def test_concurrent_appends_preserve_unique_sequences(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")

    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )

    repo = repository(database)

    def append(index: int) -> None:
        repo.append_exchange(
            binding_id="binding-1",
            business_id="business-1",
            user_content=f"user-{index}",
            assistant_content=f"assistant-{index}",
            created_at=now(),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(8)))

    with database.connection() as connection:
        rows = connection.execute(
            """
            SELECT sequence, role
            FROM whatsapp_conversation_turns
            WHERE binding_id = ?
            ORDER BY sequence ASC
            """,
            ("binding-1",),
        ).fetchall()

    assert len(rows) == 16
    assert [row["sequence"] for row in rows] == list(range(1, 17))

    for index in range(0, 16, 2):
        assert rows[index]["role"] == "user"
        assert rows[index + 1]["role"] == "assistant"


def test_v2_to_v4_migration_creates_conversation_schema(tmp_path):
    database_path = tmp_path / "migration.sqlite3"

    database = SQLiteDatabase(database_path)

    # Build the database using the current base schema, then deliberately
    # represent an existing installation at v2. initialize() must migrate
    # that installation through v3 and v4.
    database._path.parent.mkdir(parents=True, exist_ok=True)

    with database.connection() as connection:
        from app.persistence.database import BASE_SCHEMA

        connection.executescript(BASE_SCHEMA)
        connection.execute(
            """
            INSERT INTO persistence_metadata(key, value)
            VALUES('schema_version', '2')
            """
        )

    # The metadata row already exists in this test setup, so remove the
    # duplicate row that the INSERT above would otherwise create.
    with database.connection() as connection:
        connection.execute(
            """
            UPDATE persistence_metadata
            SET value = '2'
            WHERE key = 'schema_version'
            """
        )

    database.initialize()

    with database.connection() as connection:
        version = connection.execute(
            """
            SELECT value
            FROM persistence_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()["value"]

        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'whatsapp_conversation_turns'
            """
        ).fetchone()

    assert version == str(SCHEMA_VERSION)
    assert table is not None


def test_append_exchange_bounded_view_preserves_full_history(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")
    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )
    repo = repository(database)

    for index in range(3):
        repo.append_exchange(
            binding_id="binding-1",
            business_id="business-1",
            user_content=f"user-{index}",
            assistant_content=f"assistant-{index}",
            created_at=now(),
        )

    bounded = repo.append_exchange(
        binding_id="binding-1",
        business_id="business-1",
        user_content="user-3",
        assistant_content="assistant-3",
        created_at=now(),
        max_turns=2,
    )

    assert [turn.content for turn in bounded.turns] == [
        "user-3", "assistant-3"
    ]
    assert bounded.max_turns == 2

    full = repo.load_history(
        binding_id="binding-1",
        business_id="business-1",
    )
    assert len(full.turns) == 8
    assert full.turns[0].content == "user-0"
    assert full.turns[-1].content == "assistant-3"


def test_duplicate_exchange_bounded_view_preserves_full_history(tmp_path):
    database = make_database(tmp_path / "conversation.sqlite3")
    add_binding(
        database,
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id="+27111111111",
        user_id="user-1",
        business_id="business-1",
    )
    repo = repository(database)

    for index in range(3):
        repo.append_exchange(
            binding_id="binding-1",
            business_id="business-1",
            user_content=f"user-{index}",
            assistant_content=f"assistant-{index}",
            created_at=now(),
            exchange_id=f"exchange-{index}",
        )

    bounded = repo.append_exchange(
        binding_id="binding-1",
        business_id="business-1",
        user_content="duplicate user",
        assistant_content="duplicate assistant",
        created_at=now(),
        exchange_id="exchange-0",
        max_turns=2,
    )

    assert [turn.content for turn in bounded.turns] == [
        "user-2", "assistant-2"
    ]
    assert bounded.max_turns == 2

    full = repo.load_history(
        binding_id="binding-1",
        business_id="business-1",
    )
    assert len(full.turns) == 6
    assert full.turns[0].content == "user-0"
    assert full.turns[-1].content == "assistant-2"
