from datetime import datetime, timezone

import pytest

from app.assistant.conversation import ConversationRole
from app.identity.models import BusinessMembership, User, UserRole
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.voice_conversation import SQLiteVoiceConversationRepository


def make_repository(tmp_path):
    database_path = tmp_path / "voice-conversation.sqlite3"
    database = SQLiteDatabase(database_path)
    database.initialize()
    businesses = SQLiteBusinessRepository(database)
    users = SQLiteUserRepository(database)
    memberships = SQLiteMembershipRepository(database)

    businesses.save(Business(
        business_id="business-1",
        name="Business One",
        owner_name="Owner One",
        assistant_name="Assistant One",
        assistant_voice="female",
    ))
    users.save(User(
        user_id="user-1",
        display_name="User One",
        email="user1@example.com",
    ))
    users.save(User(
        user_id="user-2",
        display_name="User Two",
        email="user2@example.com",
    ))
    memberships.save(BusinessMembership(
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
    ))
    return database_path, database, SQLiteVoiceConversationRepository(database)


def test_voice_history_retains_256_turns_after_database_reopen(tmp_path):
    database_path, _, repository = make_repository(tmp_path)
    now = datetime.now(timezone.utc)
    conversation = repository.create_conversation(
        user_id="user-1",
        business_id="business-1",
        created_at=now,
        conversation_id="voice-long-1",
    )

    for number in range(128):
        history = repository.append_exchange(
            user_id="user-1",
            business_id="business-1",
            conversation_id=conversation.conversation_id,
            user_content=f"user-{number}",
            assistant_content=f"assistant-{number}",
            created_at=now,
        )

    expected = [
        item
        for number in range(128)
        for item in (f"user-{number}", f"assistant-{number}")
    ]
    assert [turn.content for turn in history.turns] == expected
    assert len(history.turns) == 256
    assert history.max_turns is None

    reopened_database = SQLiteDatabase(database_path)
    reopened_database.initialize()
    reopened_repository = SQLiteVoiceConversationRepository(reopened_database)
    reloaded = reopened_repository.load_history(
        user_id="user-1",
        business_id="business-1",
        conversation_id=conversation.conversation_id,
    )
    assert [turn.content for turn in reloaded.turns] == expected
    assert len(reloaded.turns) == 256


def test_voice_history_rejects_another_users_access(tmp_path):
    _, _, repository = make_repository(tmp_path)
    conversation = repository.create_conversation(
        user_id="user-1",
        business_id="business-1",
        created_at=datetime.now(timezone.utc),
        conversation_id="voice-private-1",
    )

    with pytest.raises(PermissionError):
        repository.load_history(
            user_id="user-2",
            business_id="business-1",
            conversation_id=conversation.conversation_id,
        )


def test_voice_standalone_turn_appends_in_sequence(tmp_path):
    _, _, repository = make_repository(tmp_path)
    now = datetime.now(timezone.utc)
    conversation = repository.create_conversation(
        user_id="user-1",
        business_id="business-1",
        created_at=now,
        conversation_id="voice-single-1",
    )
    history = repository.append_turn(
        user_id="user-1",
        business_id="business-1",
        conversation_id=conversation.conversation_id,
        role=ConversationRole.ASSISTANT,
        content="A standalone response",
        created_at=now,
    )

    assert len(history.turns) == 1
    assert history.turns[0].role is ConversationRole.ASSISTANT
    assert history.turns[0].content == "A standalone response"
