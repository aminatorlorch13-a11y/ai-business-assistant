from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.assistant.response import AssistantResponse
from app.commercial.state import CommercialStatus, BusinessCommercialState
from app.identity.models import BusinessMembership, UserRole
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.whatsapp.identity import WhatsAppIdentityError, WhatsAppIdentityResolver
from app.whatsapp.models import WhatsAppBinding
from app.whatsapp.security import (
    WhatsAppSignatureError,
    hash_sender_id,
    verify_webhook_signature,
)


SECRET = "whatsapp-test-secret"


def make_database(tmp_path):
    database = SQLiteDatabase(tmp_path / "whatsapp-attack.db")
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
                "Attack Test Business",
                "Test Owner",
                "Amina",
                "female",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(
                user_id,
                display_name,
                email
            )
            VALUES (?, ?, ?)
            """,
            (
                "user-1",
                "Attack Test User",
                "attack@example.com",
            ),
        )

    SQLiteMembershipRepository(database).save(
        BusinessMembership(
            user_id="user-1",
            business_id="business-1",
            role=UserRole.MEMBER,
        )
    )

    return database


def make_binding(
    *,
    sender_id="27820000001",
    user_id="user-1",
    business_id="business-1",
    binding_id="binding-1",
    provider="test",
    provider_account_id="account-1",
    active=True,
):
    return WhatsAppBinding(
        binding_id=binding_id,
        provider=provider,
        provider_account_id=provider_account_id,
        sender_id_hash=hash_sender_id(sender_id, SECRET),
        user_id=user_id,
        business_id=business_id,
        role=UserRole.MEMBER,
        active=active,
    )


def test_signature_rejects_uppercase_hex(tmp_path):
    raw_body = b'{"message":"hello"}'

    import hmac
    import hashlib

    digest = hmac.new(
        SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest().upper()

    with pytest.raises(WhatsAppSignatureError):
        verify_webhook_signature(
            raw_body,
            f"sha256={digest}",
            SECRET,
        )


def test_sender_hash_is_not_raw_sender_id():
    sender = "27820000001"

    hashed = hash_sender_id(sender, SECRET)

    assert hashed != sender
    assert sender not in hashed
    assert len(hashed) == 64


def test_identity_cannot_cross_provider_account(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    repository.save_binding(make_binding())

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        sender_hash_secret=SECRET,
    )

    with pytest.raises(PermissionError):
        resolver.resolve(
            provider="test",
            provider_account_id="different-account",
            sender_id="27820000001",
        )


def test_identity_cannot_cross_business_by_changing_sender_lookup(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    repository.save_binding(
        make_binding(
            sender_id="27820000001",
            business_id="business-1",
        )
    )

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        sender_hash_secret=SECRET,
    )

    tenant = resolver.resolve(
        provider="test",
        provider_account_id="account-1",
        sender_id="27820000001",
    )

    assert tenant.business_id == "business-1"
    assert tenant.principal.business_id == "business-1"


def test_inactive_binding_is_rejected(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    repository.save_binding(
        make_binding(active=False)
    )

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        sender_hash_secret=SECRET,
    )

    with pytest.raises(PermissionError):
        resolver.resolve(
            provider="test",
            provider_account_id="account-1",
            sender_id="27820000001",
        )


def test_wrong_hash_secret_cannot_resolve_sender(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    repository.save_binding(make_binding())

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        sender_hash_secret="wrong-secret",
    )

    with pytest.raises(PermissionError):
        resolver.resolve(
            provider="test",
            provider_account_id="account-1",
            sender_id="27820000001",
        )


def test_duplicate_provider_message_is_atomically_rejected(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    now = datetime.now(timezone.utc)

    first = repository.claim_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        sender_id_hash=hash_sender_id("27820000001", SECRET),
        received_at=now,
    )

    second = repository.claim_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        sender_id_hash=hash_sender_id("27820000001", SECRET),
        received_at=now,
    )

    assert first is True
    assert second is False


def test_same_message_id_on_different_provider_accounts_is_distinct(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    now = datetime.now(timezone.utc)
    sender_hash = hash_sender_id("27820000001", SECRET)

    first = repository.claim_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        sender_id_hash=sender_hash,
        received_at=now,
    )

    second = repository.claim_message(
        provider="test",
        provider_account_id="account-2",
        provider_message_id="message-1",
        sender_id_hash=sender_hash,
        received_at=now,
    )

    assert first is True
    assert second is True


def test_completed_message_contains_stored_response(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    now = datetime.now(timezone.utc)
    sender_hash = hash_sender_id("27820000001", SECRET)

    assert repository.claim_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        sender_id_hash=sender_hash,
        received_at=now,
    )

    repository.prepare_delivery(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        business_id="business-1",
        binding_id="binding-1",
        inbound_text="Confirmed.",
        response_text="Confirmed.",
    )
    repository.mark_delivery_attempted(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        attempted_at=now,
    )
    repository.mark_delivered(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        delivered_at=now,
        provider_response_message_id="outbound-1",
    )
    repository.mark_conversation_persisted(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        persisted_at=now,
    )
    repository.complete_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        completed_at=now,
    )

    record = repository.get_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
    )

    assert record is not None
    assert record.response_text == "Confirmed."
    assert record.status.value == "completed"


def test_failed_message_never_contains_success_response(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    now = datetime.now(timezone.utc)
    sender_hash = hash_sender_id("27820000001", SECRET)

    assert repository.claim_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        sender_id_hash=sender_hash,
        received_at=now,
    )

    repository.fail_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
        completed_at=now,
        error_code="provider_delivery_failed",
    )

    record = repository.get_message(
        provider="test",
        provider_account_id="account-1",
        provider_message_id="message-1",
    )

    assert record is not None
    assert record.status.value == "failed"
    assert record.response_text is None
    assert record.error_code == "provider_delivery_failed"


def test_identity_rejects_binding_without_authoritative_membership(tmp_path):
    database = SQLiteDatabase(tmp_path / "missing-membership.db")
    database.initialize()

    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "business-1",
                "Identity Attack Business",
                "Test Owner",
                "Assistant",
                "female",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "user-1",
                "Test User",
                "identity@example.com",
            ),
        )

    repository = SQLiteWhatsAppRepository(database)

    binding = WhatsAppBinding(
        binding_id="binding-1",
        provider="meta",
        provider_account_id="account-1",
        sender_id_hash=hash_sender_id("27820000001", SECRET),
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
    )
    repository.save_binding(binding)

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        sender_hash_secret=SECRET,
    )

    with pytest.raises(WhatsAppIdentityError):
        resolver.resolve(
            provider="meta",
            provider_account_id="account-1",
            sender_id="27820000001",
        )


def test_identity_uses_authoritative_membership_role_not_binding_role(tmp_path):
    database = SQLiteDatabase(tmp_path / "membership-role.db")
    database.initialize()

    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "business-1",
                "Identity Attack Business",
                "Test Owner",
                "Assistant",
                "female",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "user-1",
                "Test User",
                "identity@example.com",
            ),
        )

    membership_repository = SQLiteMembershipRepository(database)
    membership_repository.save(
        BusinessMembership(
            user_id="user-1",
            business_id="business-1",
            role=UserRole.MEMBER,
        )
    )

    repository = SQLiteWhatsAppRepository(database)

    # Deliberately forge/stale the channel binding as OWNER.
    repository.save_binding(
        WhatsAppBinding(
            binding_id="binding-1",
            provider="meta",
            provider_account_id="account-1",
            sender_id_hash=hash_sender_id("27820000002", SECRET),
            user_id="user-1",
            business_id="business-1",
            role=UserRole.OWNER,
        )
    )

    resolver = WhatsAppIdentityResolver(
        repository,
        membership_repository,
        sender_hash_secret=SECRET,
    )

    tenant = resolver.resolve(
        provider="meta",
        provider_account_id="account-1",
        sender_id="27820000002",
    )

    assert tenant.business_id == "business-1"
    assert tenant.principal.user_id == "user-1"
    assert tenant.principal.role is UserRole.MEMBER
