from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

import pytest

from app.identity.models import BusinessMembership, UserRole
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.whatsapp.identity import (
    WhatsAppIdentityError,
    WhatsAppIdentityResolver,
)
from app.whatsapp.models import WhatsAppBinding
from app.whatsapp.security import (
    WhatsAppSignatureError,
    hash_sender_id,
    verify_webhook_signature,
)


def make_database(tmp_path):
    database = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    database.initialize()

    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            ("user_1", "Owner", "owner@example.com"),
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
                "business_1",
                "Business One",
                "Owner",
                "Amina",
                "female",
            ),
        )

        connection.execute(
            """
            INSERT INTO business_memberships(user_id, business_id, role)
            VALUES (?, ?, ?)
            """,
            ("user_1", "business_1", "owner"),
        )

    SQLiteMembershipRepository(database).save(
        BusinessMembership(
            user_id="user_1",
            business_id="business_1",
            role=UserRole.OWNER,
        )
    )

    return database


def make_binding(repository, secret="sender-secret"):
    binding = WhatsAppBinding(
        binding_id="binding_1",
        provider="meta",
        provider_account_id="account_1",
        sender_id_hash=hash_sender_id("+27820000000", secret),
        user_id="user_1",
        business_id="business_1",
        role=UserRole.OWNER,
    )
    repository.save_binding(binding)
    return binding


def test_signature_verification_accepts_valid_signature():
    body = b'{"hello":"world"}'
    secret = "webhook-secret"

    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    verify_webhook_signature(
        body,
        f"sha256={expected}",
        secret,
    )


def test_signature_verification_rejects_tampered_body():
    body = b'{"hello":"world"}'
    secret = "webhook-secret"

    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    with pytest.raises(WhatsAppSignatureError):
        verify_webhook_signature(
            b'{"hello":"attacker"}',
            f"sha256={expected}",
            secret,
        )


def test_signature_verification_rejects_missing_signature():
    with pytest.raises(WhatsAppSignatureError):
        verify_webhook_signature(
            b"payload",
            "",
            "secret",
        )


def test_signature_verification_rejects_wrong_secret():
    body = b"payload"

    expected = hmac.new(
        b"correct",
        body,
        hashlib.sha256,
    ).hexdigest()

    with pytest.raises(WhatsAppSignatureError):
        verify_webhook_signature(
            body,
            f"sha256={expected}",
            "wrong",
        )


def test_sender_hash_is_deterministic_but_not_plaintext():
    result = hash_sender_id("+27820000000", "secret")

    assert result == hash_sender_id("+27820000000", "secret")
    assert "+27820000000" not in result
    assert len(result) == 64


def test_whatsapp_binding_resolves_to_trusted_tenant(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)
    make_binding(repository)

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        "sender-secret",
    )

    tenant = resolver.resolve(
        provider="meta",
        provider_account_id="account_1",
        sender_id="+27820000000",
    )

    assert tenant.business_id == "business_1"
    assert tenant.principal.business_id == "business_1"
    assert tenant.principal.user_id == "user_1"
    assert tenant.principal.role is UserRole.OWNER
    assert tenant.principal.session_id.startswith("whatsapp:")


def test_unknown_sender_cannot_select_business(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)
    make_binding(repository)

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        "sender-secret",
    )

    with pytest.raises(WhatsAppIdentityError):
        resolver.resolve(
            provider="meta",
            provider_account_id="account_1",
            sender_id="+27829999999",
        )


def test_wrong_provider_account_cannot_use_existing_binding(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)
    make_binding(repository)

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        "sender-secret",
    )

    with pytest.raises(WhatsAppIdentityError):
        resolver.resolve(
            provider="meta",
            provider_account_id="different_account",
            sender_id="+27820000000",
        )


def test_inactive_binding_cannot_execute(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)
    binding = make_binding(repository)

    assert repository.deactivate_binding(binding.binding_id) is True

    resolver = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        "sender-secret",
    )

    with pytest.raises(WhatsAppIdentityError):
        resolver.resolve(
            provider="meta",
            provider_account_id="account_1",
            sender_id="+27820000000",
        )


def test_duplicate_provider_message_id_is_rejected(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    now = datetime.now(timezone.utc)

    first = repository.claim_message(
        provider="meta",
        provider_account_id="account_1",
        provider_message_id="message_1",
        sender_id_hash="hash",
        received_at=now,
    )

    second = repository.claim_message(
        provider="meta",
        provider_account_id="account_1",
        provider_message_id="message_1",
        sender_id_hash="hash",
        received_at=now,
    )

    assert first is True
    assert second is False


def test_same_message_id_from_different_provider_accounts_is_independent(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    now = datetime.now(timezone.utc)

    assert repository.claim_message(
        "meta",
        "account_1",
        "message_1",
        "hash",
        now,
    )

    assert repository.claim_message(
        "meta",
        "account_2",
        "message_1",
        "hash",
        now,
    )


def test_database_schema_contains_whatsapp_tables(tmp_path):
    database = make_database(tmp_path)

    with database.connection() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

    assert "whatsapp_bindings" in tables
    assert "whatsapp_inbound_messages" in tables


def test_sender_hash_secret_separates_business_identity(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteWhatsAppRepository(database)

    make_binding(repository, secret="secret-a")

    resolver_with_wrong_secret = WhatsAppIdentityResolver(
        repository,
        SQLiteMembershipRepository(database),
        "secret-b",
    )

    with pytest.raises(WhatsAppIdentityError):
        resolver_with_wrong_secret.resolve(
            "meta",
            "account_1",
            "+27820000000",
        )
