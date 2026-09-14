from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.identity.models import BusinessMembership, User, UserRole
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.persistence.whatsapp_conversation import (
    SQLiteWhatsAppConversationRepository,
)
from app.whatsapp.models import WhatsAppBinding
from app.whatsapp.security import hash_sender_id


BUSINESS_ID = "delivery-business"
USER_ID = "delivery-user"
PROVIDER = "delivery-provider"
ACCOUNT_ID = "delivery-account"
SENDER_ID = "27821111111"
SENDER_SECRET = "delivery-secret"


def make_database():
    temporary_directory = TemporaryDirectory(
        prefix="ai-business-assistant-delivery-test-"
    )
    database = SQLiteDatabase(
        Path(temporary_directory.name) / "delivery.sqlite3"
    )
    database.initialize()
    return database, temporary_directory


def seed(database):
    SQLiteBusinessRepository(database).save(
        Business(
            business_id=BUSINESS_ID,
            name="Delivery Test Business",
            owner_name="Delivery Owner",
            assistant_name="Delivery Assistant",
            assistant_voice="female",
        )
    )

    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO users (user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (USER_ID, "Delivery User", "delivery@example.com"),
        )
        connection.commit()

    SQLiteMembershipRepository(database).save(
        BusinessMembership(
            user_id=USER_ID,
            business_id=BUSINESS_ID,
            role=UserRole.OWNER,
        )
    )

    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            business_id=BUSINESS_ID,
            status=CommercialStatus.ACTIVE,
        )
    )

    SQLiteWhatsAppRepository(database).save_binding(
        WhatsAppBinding(
            binding_id="delivery-binding",
            provider=PROVIDER,
            provider_account_id=ACCOUNT_ID,
            sender_id_hash=hash_sender_id(
                SENDER_ID,
                SENDER_SECRET,
            ),
            user_id=USER_ID,
            business_id=BUSINESS_ID,
            role=UserRole.OWNER,
            active=True,
        )
    )


def test_delivery_states_are_distinct():
    from app.delivery.state import DeliveryState

    assert DeliveryState.PROCESSING.value == "processing"
    assert DeliveryState.DELIVERY_PENDING.value == "delivery_pending"
    assert DeliveryState.DELIVERY_ATTEMPTED.value == "delivery_attempted"
    assert DeliveryState.DELIVERED.value == "delivered"
    assert DeliveryState.CONVERSATION_PERSISTED.value == (
        "conversation_persisted"
    )
    assert DeliveryState.COMPLETED.value == "completed"
    assert DeliveryState.FAILED.value == "failed"
    assert DeliveryState.DELIVERY_UNKNOWN.value == "delivery_unknown"


def test_delivery_attempted_is_not_safely_retryable():
    database, temporary_directory = make_database()
    try:
        seed(database)
        repository = SQLiteWhatsAppRepository(database)

        assert repository.claim_message(
            PROVIDER,
            ACCOUNT_ID,
            "message-attempted",
            hash_sender_id(SENDER_ID, SENDER_SECRET),
            datetime.now(timezone.utc),
            inbound_text="hello",
        )

        repository.prepare_delivery(
            provider=PROVIDER,
            provider_account_id=ACCOUNT_ID,
            provider_message_id="message-attempted",
            business_id=BUSINESS_ID,
            binding_id="delivery-binding",
            inbound_text="hello",
            response_text="reply",
        )

        repository.mark_delivery_attempted(
            provider=PROVIDER,
            provider_account_id=ACCOUNT_ID,
            provider_message_id="message-attempted",
            attempted_at=datetime.now(timezone.utc),
        )

        record = repository.get_message(
            PROVIDER,
            ACCOUNT_ID,
            "message-attempted",
        )

        assert record is not None
        assert record.status.value == "delivery_attempted"
        assert record.delivery_attempted_at is not None
    finally:
        temporary_directory.cleanup()


def test_delivery_unknown_is_explicitly_non_retryable_without_reconciliation():
    database, temporary_directory = make_database()
    try:
        seed(database)
        repository = SQLiteWhatsAppRepository(database)

        assert repository.claim_message(
            PROVIDER,
            ACCOUNT_ID,
            "message-unknown",
            hash_sender_id(SENDER_ID, SENDER_SECRET),
            datetime.now(timezone.utc),
            inbound_text="hello",
        )

        repository.prepare_delivery(
            provider=PROVIDER,
            provider_account_id=ACCOUNT_ID,
            provider_message_id="message-unknown",
            business_id=BUSINESS_ID,
            binding_id="delivery-binding",
            inbound_text="hello",
            response_text="reply",
        )

        repository.mark_delivery_unknown(
            provider=PROVIDER,
            provider_account_id=ACCOUNT_ID,
            provider_message_id="message-unknown",
            error_code="delivery_outcome_unknown",
        )

        record = repository.get_message(
            PROVIDER,
            ACCOUNT_ID,
            "message-unknown",
        )

        assert record is not None
        assert record.status.value == "delivery_unknown"
        assert record.error_code == "delivery_outcome_unknown"
    finally:
        temporary_directory.cleanup()


def test_exchange_id_makes_conversation_persistence_idempotent():
    database, temporary_directory = make_database()
    try:
        seed(database)

        repository = SQLiteWhatsAppConversationRepository(database)
        created_at = datetime.now(timezone.utc)

        first = repository.append_exchange(
            binding_id="delivery-binding",
            business_id=BUSINESS_ID,
            user_content="hello",
            assistant_content="reply",
            created_at=created_at,
            exchange_id="message-idempotent",
        )

        second = repository.append_exchange(
            binding_id="delivery-binding",
            business_id=BUSINESS_ID,
            user_content="hello",
            assistant_content="reply",
            created_at=created_at,
            exchange_id="message-idempotent",
        )

        assert first == second

        history = repository.load_history(
            binding_id="delivery-binding",
            business_id=BUSINESS_ID,
        )

        assert len(history.turns) == 2
        assert history.turns[0].content == "hello"
        assert history.turns[1].content == "reply"
    finally:
        temporary_directory.cleanup()


def test_same_exchange_id_cannot_change_existing_exchange():
    database, temporary_directory = make_database()
    try:
        seed(database)

        repository = SQLiteWhatsAppConversationRepository(database)
        created_at = datetime.now(timezone.utc)

        repository.append_exchange(
            binding_id="delivery-binding",
            business_id=BUSINESS_ID,
            user_content="original",
            assistant_content="original reply",
            created_at=created_at,
            exchange_id="immutable-exchange",
        )

        try:
            repository.append_exchange(
                binding_id="delivery-binding",
                business_id=BUSINESS_ID,
                user_content="tampered",
                assistant_content="tampered reply",
                created_at=created_at,
                exchange_id="immutable-exchange",
            )
        except Exception:
            pass

        history = repository.load_history(
            binding_id="delivery-binding",
            business_id=BUSINESS_ID,
        )

        assert len(history.turns) == 2
        assert history.turns[0].content == "original"
        assert history.turns[1].content == "original reply"
    finally:
        temporary_directory.cleanup()
