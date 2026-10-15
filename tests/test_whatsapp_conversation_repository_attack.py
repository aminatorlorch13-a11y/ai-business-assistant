from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from app.identity.models import BusinessMembership, User, UserRole
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.persistence.whatsapp_conversation import (
    SQLiteWhatsAppConversationRepository,
)
from app.whatsapp.models import WhatsAppBinding
from app.whatsapp.security import hash_sender_id


BUSINESS_1 = "business-1"
BUSINESS_2 = "business-2"

USER_1 = "user-1"
USER_2 = "user-2"

PROVIDER = "test-provider"

ACCOUNT_1 = "account-1"
ACCOUNT_2 = "account-2"

SENDER_1 = "27820000001"
SENDER_2 = "27820000002"
SENDER_3 = "27820000003"

SENDER_SECRET = "repository-test-secret"


def make_database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "whatsapp-conversation.sqlite3")
    database.initialize()
    return database


def seed_business(
    database: SQLiteDatabase,
    *,
    business_id: str,
    user_id: str,
) -> None:
    SQLiteBusinessRepository(database).save(
        Business(
            business_id=business_id,
            name=f"Business {business_id}",
            owner_name=f"Owner {user_id}",
            assistant_name="Test Assistant",
            assistant_voice="female",
        )
    )

    SQLiteUserRepository(database).save(
        User(
            user_id=user_id,
            display_name=f"Test User {user_id}",
            email=f"{user_id}@example.com",
        )
    )

    SQLiteMembershipRepository(database).save(
        BusinessMembership(
            user_id=user_id,
            business_id=business_id,
            role=UserRole.OWNER,
        )
    )


def seed_binding(
    database: SQLiteDatabase,
    *,
    binding_id: str,
    business_id: str,
    user_id: str,
    provider_account_id: str,
    sender_id: str,
    active: bool = True,
) -> None:
    SQLiteWhatsAppRepository(database).save_binding(
        WhatsAppBinding(
            binding_id=binding_id,
            provider=PROVIDER,
            provider_account_id=provider_account_id,
            sender_id_hash=hash_sender_id(
                sender_id,
                SENDER_SECRET,
            ),
            user_id=user_id,
            business_id=business_id,
            role=UserRole.OWNER,
            active=active,
        )
    )


def make_repository(
    tmp_path,
) -> tuple[
    SQLiteDatabase,
    SQLiteWhatsAppConversationRepository,
]:
    database = make_database(tmp_path)

    seed_business(
        database,
        business_id=BUSINESS_1,
        user_id=USER_1,
    )

    seed_business(
        database,
        business_id=BUSINESS_2,
        user_id=USER_2,
    )

    # Two independent WhatsApp identities in the SAME business.
    seed_binding(
        database,
        binding_id="binding-1",
        business_id=BUSINESS_1,
        user_id=USER_1,
        provider_account_id=ACCOUNT_1,
        sender_id=SENDER_1,
    )

    seed_binding(
        database,
        binding_id="binding-2",
        business_id=BUSINESS_1,
        user_id=USER_1,
        provider_account_id=ACCOUNT_2,
        sender_id=SENDER_2,
    )

    # Separate business identity.
    seed_binding(
        database,
        binding_id="binding-business-2",
        business_id=BUSINESS_2,
        user_id=USER_2,
        provider_account_id="account-business-2",
        sender_id=SENDER_3,
    )

    return database, SQLiteWhatsAppConversationRepository(database)


def now() -> datetime:
    return datetime.now(timezone.utc)


def append_exchange(
    repository: SQLiteWhatsAppConversationRepository,
    *,
    binding_id: str,
    business_id: str,
    number: int,
):
    return repository.append_exchange(
        binding_id=binding_id,
        business_id=business_id,
        user_content=f"user message {number}",
        assistant_content=f"assistant response {number}",
        created_at=now(),
    )


def test_cross_binding_history_isolation(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    append_exchange(
        repository,
        binding_id="binding-1",
        business_id=BUSINESS_1,
        number=1,
    )

    # Binding 2 belongs to the same business, but must not see
    # Binding 1's conversation history.
    history = repository.load_history(
        binding_id="binding-2",
        business_id=BUSINESS_1,
    )

    assert history.business_id == BUSINESS_1
    assert history.turns == ()

    # Binding 2 may legitimately create its OWN conversation.
    append_exchange(
        repository,
        binding_id="binding-2",
        business_id=BUSINESS_1,
        number=2,
    )

    binding_1_history = repository.load_history(
        binding_id="binding-1",
        business_id=BUSINESS_1,
    )

    binding_2_history = repository.load_history(
        binding_id="binding-2",
        business_id=BUSINESS_1,
    )

    assert [turn.content for turn in binding_1_history.turns] == [
        "user message 1",
        "assistant response 1",
    ]

    assert [turn.content for turn in binding_2_history.turns] == [
        "user message 2",
        "assistant response 2",
    ]


def test_cross_business_history_access_is_rejected(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    append_exchange(
        repository,
        binding_id="binding-1",
        business_id=BUSINESS_1,
        number=1,
    )

    with pytest.raises(PermissionError):
        repository.load_history(
            binding_id="binding-1",
            business_id=BUSINESS_2,
        )

    with pytest.raises(PermissionError):
        repository.append_exchange(
            binding_id="binding-1",
            business_id=BUSINESS_2,
            user_content="forged user message",
            assistant_content="forged assistant response",
            created_at=now(),
        )


def test_forged_binding_and_business_pair_is_rejected(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    with pytest.raises(PermissionError):
        repository.load_history(
            binding_id="binding-business-2",
            business_id=BUSINESS_1,
        )

    with pytest.raises(PermissionError):
        repository.load_history(
            binding_id="binding-1",
            business_id=BUSINESS_2,
        )

    with pytest.raises(PermissionError):
        repository.append_exchange(
            binding_id="binding-business-2",
            business_id=BUSINESS_1,
            user_content="forged",
            assistant_content="forged",
            created_at=now(),
        )


def test_inactive_binding_cannot_load_or_append_history(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    SQLiteWhatsAppRepository(database).deactivate_binding("binding-1")

    with pytest.raises(PermissionError):
        repository.load_history(
            binding_id="binding-1",
            business_id=BUSINESS_1,
        )

    with pytest.raises(PermissionError):
        repository.append_exchange(
            binding_id="binding-1",
            business_id=BUSINESS_1,
            user_content="should fail",
            assistant_content="should fail",
            created_at=now(),
        )


def test_unknown_binding_cannot_load_or_append_history(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    with pytest.raises(PermissionError):
        repository.load_history(
            binding_id="does-not-exist",
            business_id=BUSINESS_1,
        )

    with pytest.raises(PermissionError):
        repository.append_exchange(
            binding_id="does-not-exist",
            business_id=BUSINESS_1,
            user_content="should fail",
            assistant_content="should fail",
            created_at=now(),
        )


def test_history_retains_all_turns_and_keeps_complete_exchanges(
    tmp_path,
) -> None:
    database, repository = make_repository(tmp_path)

    for number in range(1, 20):
        append_exchange(
            repository,
            binding_id="binding-1",
            business_id=BUSINESS_1,
            number=number,
        )

    history = repository.load_history(
        binding_id="binding-1",
        business_id=BUSINESS_1,
    )

    assert len(history.turns) == 38
    assert len(history.turns) % 2 == 0

    assert history.turns[0].content == "user message 1"
    assert history.turns[1].content == "assistant response 1"

    assert history.turns[-2].content == "user message 19"
    assert history.turns[-1].content == "assistant response 19"

    for index in range(0, len(history.turns), 2):
        assert history.turns[index].role.value == "user"
        assert history.turns[index + 1].role.value == "assistant"


@pytest.mark.parametrize(
    "max_turns",
    [0, 1, 3, 25, -2, True, False],
)
def test_invalid_max_turns_is_rejected(tmp_path, max_turns) -> None:
    database, repository = make_repository(tmp_path)

    with pytest.raises((TypeError, ValueError)):
        repository.load_history(
            binding_id="binding-1",
            business_id=BUSINESS_1,
            max_turns=max_turns,
        )


@pytest.mark.parametrize(
    "created_at",
    [
        datetime.now(),
        "2026-01-01T00:00:00Z",
        None,
    ],
)
def test_invalid_timestamp_is_rejected(tmp_path, created_at) -> None:
    database, repository = make_repository(tmp_path)

    with pytest.raises(ValueError):
        repository.append_exchange(
            binding_id="binding-1",
            business_id=BUSINESS_1,
            user_content="hello",
            assistant_content="hello back",
            created_at=created_at,
        )


@pytest.mark.parametrize(
    "binding_id",
    [
        "",
        "   ",
        "x" * 129,
    ],
)
def test_invalid_binding_identifier_is_rejected(
    tmp_path,
    binding_id: str,
) -> None:
    database, repository = make_repository(tmp_path)

    with pytest.raises(ValueError):
        repository.load_history(
            binding_id=binding_id,
            business_id=BUSINESS_1,
        )


@pytest.mark.parametrize(
    "business_id",
    [
        "",
        "   ",
        "x" * 129,
    ],
)
def test_invalid_business_identifier_is_rejected(
    tmp_path,
    business_id: str,
) -> None:
    database, repository = make_repository(tmp_path)

    with pytest.raises(ValueError):
        repository.load_history(
            binding_id="binding-1",
            business_id=business_id,
        )


@pytest.mark.parametrize(
    "user_content,assistant_content",
    [
        ("", "response"),
        ("   ", "response"),
        ("message", ""),
        ("message", "   "),
    ],
)
def test_empty_exchange_content_is_rejected(
    tmp_path,
    user_content: str,
    assistant_content: str,
) -> None:
    database, repository = make_repository(tmp_path)

    with pytest.raises(ValueError):
        repository.append_exchange(
            binding_id="binding-1",
            business_id=BUSINESS_1,
            user_content=user_content,
            assistant_content=assistant_content,
            created_at=now(),
        )


def test_successive_appends_preserve_order(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    for number in range(1, 6):
        append_exchange(
            repository,
            binding_id="binding-1",
            business_id=BUSINESS_1,
            number=number,
        )

    history = repository.load_history(
        binding_id="binding-1",
        business_id=BUSINESS_1,
    )

    expected = [
        "user message 1",
        "assistant response 1",
        "user message 2",
        "assistant response 2",
        "user message 3",
        "assistant response 3",
        "user message 4",
        "assistant response 4",
        "user message 5",
        "assistant response 5",
    ]

    assert [turn.content for turn in history.turns] == expected


def test_loading_history_has_no_side_effects(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    append_exchange(
        repository,
        binding_id="binding-1",
        business_id=BUSINESS_1,
        number=1,
    )

    first = repository.load_history(
        binding_id="binding-1",
        business_id=BUSINESS_1,
    )

    second = repository.load_history(
        binding_id="binding-1",
        business_id=BUSINESS_1,
    )

    assert [turn.content for turn in first.turns] == [
        turn.content for turn in second.turns
    ]

    assert len(second.turns) == 2


def test_binding_deletion_cascades_conversation_history(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    append_exchange(
        repository,
        binding_id="binding-1",
        business_id=BUSINESS_1,
        number=1,
    )

    with database.transaction() as connection:
        connection.execute(
            "DELETE FROM whatsapp_bindings WHERE binding_id = ?",
            ("binding-1",),
        )

    with pytest.raises(PermissionError):
        repository.load_history(
            binding_id="binding-1",
            business_id=BUSINESS_1,
        )

    with database.connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM whatsapp_conversation_turns
            WHERE binding_id = ?
            """,
            ("binding-1",),
        ).fetchone()

    assert int(row["count"]) == 0


def test_raw_sender_identifier_is_not_stored_in_conversation_table(
    tmp_path,
) -> None:
    database, repository = make_repository(tmp_path)

    append_exchange(
        repository,
        binding_id="binding-1",
        business_id=BUSINESS_1,
        number=1,
    )

    with database.connection() as connection:
        columns = connection.execute(
            "PRAGMA table_info(whatsapp_conversation_turns)"
        ).fetchall()

    column_names = {row["name"] for row in columns}

    assert "sender_id" not in column_names
    assert "phone_number" not in column_names
    assert "sender_id_hash" not in column_names


def test_same_business_bindings_have_independent_history(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    append_exchange(
        repository,
        binding_id="binding-1",
        business_id=BUSINESS_1,
        number=1,
    )

    append_exchange(
        repository,
        binding_id="binding-2",
        business_id=BUSINESS_1,
        number=2,
    )

    first_history = repository.load_history(
        binding_id="binding-1",
        business_id=BUSINESS_1,
    )

    second_history = repository.load_history(
        binding_id="binding-2",
        business_id=BUSINESS_1,
    )

    assert [turn.content for turn in first_history.turns] == [
        "user message 1",
        "assistant response 1",
    ]

    assert [turn.content for turn in second_history.turns] == [
        "user message 2",
        "assistant response 2",
    ]


def test_concurrent_appends_preserve_complete_exchange_pairs(
    tmp_path,
) -> None:
    database, repository = make_repository(tmp_path)

    def worker(number: int) -> None:
        append_exchange(
            repository,
            binding_id="binding-1",
            business_id=BUSINESS_1,
            number=number,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, range(1, 21)))

    history = repository.load_history(
        binding_id="binding-1",
        business_id=BUSINESS_1,
    )

    assert len(history.turns) == 40
    assert len(history.turns) % 2 == 0

    for index in range(0, len(history.turns), 2):
        user_turn = history.turns[index]
        assistant_turn = history.turns[index + 1]

        assert user_turn.role.value == "user"
        assert assistant_turn.role.value == "assistant"

        assert user_turn.content.startswith("user message ")
        assert assistant_turn.content.startswith("assistant response ")


def test_database_has_expected_conversation_foreign_keys(tmp_path) -> None:
    database, repository = make_repository(tmp_path)

    with database.connection() as connection:
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(whatsapp_conversation_turns)"
        ).fetchall()

    relationships = {
        (
            row["table"],
            row["from"],
            row["to"],
            row["on_delete"],
        )
        for row in foreign_keys
    }

    assert (
        "whatsapp_bindings",
        "binding_id",
        "binding_id",
        "CASCADE",
    ) in relationships

    assert (
        "businesses",
        "business_id",
        "business_id",
        "CASCADE",
    ) in relationships
