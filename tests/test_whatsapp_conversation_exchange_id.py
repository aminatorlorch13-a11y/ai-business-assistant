from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

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


BUSINESS_ID = "exchange-business"
USER_ID = "exchange-user"
SENDER_ID = "27822222222"
SECRET = "exchange-secret"


def make_repository():
    temporary_directory = TemporaryDirectory(
        prefix="ai-business-assistant-exchange-test-"
    )

    database = SQLiteDatabase(
        Path(temporary_directory.name) / "exchange.sqlite3"
    )
    database.initialize()

    SQLiteBusinessRepository(database).save(
        Business(
            business_id=BUSINESS_ID,
            name="Exchange Business",
            owner_name="Exchange Owner",
            assistant_name="Exchange Assistant",
            assistant_voice="female",
        )
    )

    SQLiteUserRepository(database).save(
        User(
            user_id=USER_ID,
            display_name="Exchange User",
            email="exchange@example.com",
        )
    )

    SQLiteMembershipRepository(database).save(
        BusinessMembership(
            user_id=USER_ID,
            business_id=BUSINESS_ID,
            role=UserRole.OWNER,
        )
    )

    SQLiteWhatsAppRepository(database).save_binding(
        WhatsAppBinding(
            binding_id="exchange-binding",
            provider="exchange-provider",
            provider_account_id="exchange-account",
            sender_id_hash=hash_sender_id(
                SENDER_ID,
                SECRET,
            ),
            user_id=USER_ID,
            business_id=BUSINESS_ID,
            role=UserRole.OWNER,
            active=True,
        )
    )

    return (
        database,
        SQLiteWhatsAppConversationRepository(database),
        temporary_directory,
    )


def test_exchange_id_replay_does_not_duplicate_turns():
    database, repository, temporary_directory = make_repository()
    try:
        timestamp = datetime.now(timezone.utc)

        for _ in range(2):
            repository.append_exchange(
                binding_id="exchange-binding",
                business_id=BUSINESS_ID,
                user_content="same inbound",
                assistant_content="same response",
                created_at=timestamp,
                exchange_id="provider-message-1",
            )

        history = repository.load_history(
            binding_id="exchange-binding",
            business_id=BUSINESS_ID,
        )

        assert len(history.turns) == 2
    finally:
        temporary_directory.cleanup()


def test_exchange_id_is_scoped_to_binding():
    database, repository, temporary_directory = make_repository()
    try:
        timestamp = datetime.now(timezone.utc)

        repository.append_exchange(
            binding_id="exchange-binding",
            business_id=BUSINESS_ID,
            user_content="binding one",
            assistant_content="response one",
            created_at=timestamp,
            exchange_id="same-provider-message",
        )

        SQLiteWhatsAppRepository(database).save_binding(
            WhatsAppBinding(
                binding_id="exchange-binding-2",
                provider="exchange-provider",
                provider_account_id="exchange-account-2",
                sender_id_hash=hash_sender_id(
                    "27823333333",
                    SECRET,
                ),
                user_id=USER_ID,
                business_id=BUSINESS_ID,
                role=UserRole.OWNER,
                active=True,
            )
        )

        repository.append_exchange(
            binding_id="exchange-binding-2",
            business_id=BUSINESS_ID,
            user_content="binding two",
            assistant_content="response two",
            created_at=timestamp,
            exchange_id="same-provider-message",
        )

        first = repository.load_history(
            binding_id="exchange-binding",
            business_id=BUSINESS_ID,
        )
        second = repository.load_history(
            binding_id="exchange-binding-2",
            business_id=BUSINESS_ID,
        )

        assert [turn.content for turn in first.turns] == [
            "binding one",
            "response one",
        ]
        assert [turn.content for turn in second.turns] == [
            "binding two",
            "response two",
        ]
    finally:
        temporary_directory.cleanup()
