from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.assistant.capability import Capability
from app.assistant.capability_confirmation import CapabilityConfirmation
from app.assistant.execution import CapabilityExecutionRequest
from app.identity.models import UserRole
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_db(tmp_path):
    db = SQLiteDatabase(tmp_path / "confirmation.db")
    db.initialize()
    return db


def make_request(
    *,
    business_id: str = "business-1",
    capability: Capability = Capability.MEMORY,
    operation: str = "delete",
    arguments: dict | None = None,
    reason: str = "User requested deletion.",
    channel: str | None = "web",
    integration: str | None = None,
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability=capability,
        operation=operation,
        business_id=business_id,
        arguments=arguments if arguments is not None else {"memory_id": "memory-1"},
        reason=reason,
        channel=channel,
        integration=integration,
    )


def make_confirmation(
    *,
    request: CapabilityExecutionRequest | None = None,
    confirmation_id: str = "confirmation-1",
    session_id_hash: str = "session-hash-1",
    user_id: str = "user-1",
    business_id: str = "business-1",
    role: UserRole = UserRole.OWNER,
    created_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> CapabilityConfirmation:
    if request is None:
        request = make_request(business_id=business_id)

    return CapabilityConfirmation(
        confirmation_id=confirmation_id,
        session_id_hash=session_id_hash,
        user_id=user_id,
        business_id=business_id,
        role=role,
        request=request,
        created_at=created_at,
        expires_at=(
            expires_at
            if expires_at is not None
            else created_at + timedelta(minutes=5)
        ),
    )


def seed_business_and_user(db: SQLiteDatabase) -> None:
    with db.transaction() as connection:
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
                "Confirmation Test Business",
                "Owner",
                "Assistant",
                "calm",
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
                "Test User",
                "user@example.com",
            ),
        )


def test_fresh_database_is_current_schema(tmp_path):
    db = make_db(tmp_path)

    assert SCHEMA_VERSION == 14

    with db.connection() as connection:
        version = connection.execute(
            """
            SELECT value
            FROM persistence_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()[0]

    assert int(version) == SCHEMA_VERSION


def test_confirmation_requires_matching_request_business():
    request = make_request(business_id="business-2")

    with pytest.raises(ValueError, match="business_id"):
        make_confirmation(
            request=request,
            business_id="business-1",
        )


@pytest.mark.parametrize(
    "field",
    ["confirmation_id", "session_id_hash", "user_id", "business_id"],
)
def test_confirmation_rejects_empty_identity_fields(field):
    values = {
        "confirmation_id": "confirmation-1",
        "session_id_hash": "session-hash-1",
        "user_id": "user-1",
        "business_id": "business-1",
    }
    values[field] = "   "

    with pytest.raises(ValueError, match=field):
        CapabilityConfirmation(
            confirmation_id=values["confirmation_id"],
            session_id_hash=values["session_id_hash"],
            user_id=values["user_id"],
            business_id=values["business_id"],
            role=UserRole.OWNER,
            request=make_request(),
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )


def test_confirmation_rejects_invalid_role():
    with pytest.raises(TypeError, match="role"):
        CapabilityConfirmation(
            confirmation_id="confirmation-1",
            session_id_hash="session-hash-1",
            user_id="user-1",
            business_id="business-1",
            role="owner",  # type: ignore[arg-type]
            request=make_request(),
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )


def test_confirmation_rejects_non_increasing_expiry():
    with pytest.raises(ValueError, match="expires_at"):
        make_confirmation(
            created_at=NOW,
            expires_at=NOW,
        )


def test_confirmation_pending_and_expiry_state():
    confirmation = make_confirmation()

    assert confirmation.is_pending(NOW)
    assert not confirmation.is_expired(NOW)

    expiry = confirmation.expires_at

    assert confirmation.is_expired(expiry)
    assert not confirmation.is_pending(expiry)


def test_confirmation_cannot_be_both_consumed_and_revoked():
    with pytest.raises(ValueError, match="both consumed and revoked"):
        CapabilityConfirmation(
            confirmation_id="confirmation-1",
            session_id_hash="session-hash-1",
            user_id="user-1",
            business_id="business-1",
            role=UserRole.OWNER,
            request=make_request(),
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            consumed_at=NOW + timedelta(minutes=1),
            revoked_at=NOW + timedelta(minutes=2),
        )


def test_repository_round_trip_preserves_exact_request(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    request = make_request(
        arguments={
            "memory_id": "memory-42",
            "content": "Important client information",
            "nested": {"enabled": True, "items": [1, 2, 3]},
            "unicode": "Café",
        },
        reason="Delete the exact memory requested by the user.",
        channel="web",
        integration="internal",
    )
    confirmation = make_confirmation(request=request)

    repository.save(confirmation)

    loaded = repository.get("confirmation-1")

    assert loaded is not None
    assert loaded == confirmation
    assert loaded.request.arguments == request.arguments
    assert loaded.request.capability is Capability.MEMORY
    assert loaded.request.operation == "delete"
    assert loaded.request.business_id == "business-1"
    assert loaded.request.reason == request.reason
    assert loaded.request.channel == "web"
    assert loaded.request.integration == "internal"


def test_repository_rejects_non_confirmation(tmp_path):
    db = make_db(tmp_path)
    repository = SQLiteCapabilityConfirmationRepository(db)

    with pytest.raises(TypeError, match="CapabilityConfirmation"):
        repository.save(object())  # type: ignore[arg-type]


def test_get_missing_confirmation_returns_none(tmp_path):
    db = make_db(tmp_path)
    repository = SQLiteCapabilityConfirmationRepository(db)

    assert repository.get("does-not-exist") is None


def test_consume_requires_exact_session_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    result = repository.consume(
        "confirmation-1",
        session_id_hash="different-session",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is None
    assert repository.get("confirmation-1") is not None
    assert repository.get("confirmation-1").consumed_at is None


def test_consume_requires_exact_user_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="different-user",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is None


def test_consume_requires_exact_business_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="different-business",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is None


def test_consume_requires_exact_role_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation(role=UserRole.OWNER))

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.ADMIN,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is None


def test_consume_rejects_expired_confirmation(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    repository.save(
        make_confirmation(
            expires_at=NOW + timedelta(minutes=5),
        )
    )

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=5),
    )

    assert result is None
    assert repository.get("confirmation-1").consumed_at is None


def test_consume_is_single_use(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    first = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    second = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=2),
    )

    assert first is not None
    assert first.consumed_at == NOW + timedelta(minutes=1)
    assert second is None


def test_revoke_requires_exact_role_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation(role=UserRole.OWNER))

    result = repository.revoke(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.ADMIN,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is False
    assert repository.get("confirmation-1").revoked_at is None


def test_revoke_requires_exact_session_user_and_business(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    result = repository.revoke(
        "confirmation-1",
        session_id_hash="wrong-session",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is False
    assert repository.get("confirmation-1").revoked_at is None


def test_revoke_is_single_transition(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    first = repository.revoke(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    second = repository.revoke(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=2),
    )

    loaded = repository.get("confirmation-1")

    assert first is True
    assert second is False
    assert loaded.revoked_at == NOW + timedelta(minutes=1)


def test_revoked_confirmation_cannot_be_consumed(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    assert repository.revoke(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=2),
    )

    assert result is None


def test_consumed_confirmation_cannot_be_revoked(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)
    repository.save(make_confirmation())

    assert repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    ) is not None

    assert repository.revoke(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=2),
    ) is False


def test_repository_rejects_duplicate_confirmation_id(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    repository.save(make_confirmation())

    with pytest.raises(Exception):
        repository.save(
            make_confirmation(
                request=make_request(
                    arguments={"memory_id": "different-memory"}
                )
            )
        )


def test_consume_requires_exact_channel_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    repository.save(
        make_confirmation(
            request=make_request(channel="web"),
        )
    )

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="whatsapp",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is None
    loaded = repository.get("confirmation-1")
    assert loaded is not None
    assert loaded.consumed_at is None


def test_consume_requires_exact_integration_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    repository.save(
        make_confirmation(
            request=make_request(
                channel="web",
                integration="internal",
            )
        )
    )

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration="different-integration",
        now=NOW + timedelta(minutes=1),
    )

    assert result is None
    loaded = repository.get("confirmation-1")
    assert loaded is not None
    assert loaded.consumed_at is None


def test_consume_allows_matching_none_integration(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    repository.save(
        make_confirmation(
            request=make_request(
                channel="web",
                integration=None,
            )
        )
    )

    result = repository.consume(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is not None


def test_revoke_requires_exact_channel_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    repository.save(
        make_confirmation(
            request=make_request(channel="web"),
        )
    )

    result = repository.revoke(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="whatsapp",
        integration=None,
        now=NOW + timedelta(minutes=1),
    )

    assert result is False
    loaded = repository.get("confirmation-1")
    assert loaded is not None
    assert loaded.revoked_at is None


def test_revoke_requires_exact_integration_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    repository.save(
        make_confirmation(
            request=make_request(
                channel="web",
                integration="internal",
            )
        )
    )

    result = repository.revoke(
        "confirmation-1",
        session_id_hash="session-hash-1",
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        channel="web",
        integration="different-integration",
        now=NOW + timedelta(minutes=1),
    )

    assert result is False
    loaded = repository.get("confirmation-1")
    assert loaded is not None
    assert loaded.revoked_at is None

def test_save_exclusive_replaces_pending_confirmation_for_exact_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    first = make_confirmation(
        confirmation_id="confirmation-1",
        request=make_request(channel="web", integration=None),
    )
    second = make_confirmation(
        confirmation_id="confirmation-2",
        request=make_request(channel="web", integration=None),
    )

    repository.save_exclusive(first)
    repository.save_exclusive(second)

    first_loaded = repository.get("confirmation-1")
    second_loaded = repository.get("confirmation-2")

    assert first_loaded is not None
    assert first_loaded.revoked_at is not None
    assert second_loaded is not None
    assert second_loaded.revoked_at is None
    assert second_loaded.consumed_at is None


def test_save_exclusive_does_not_revoke_different_channel_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    web_confirmation = make_confirmation(
        confirmation_id="confirmation-1",
        request=make_request(channel="web", integration=None),
    )
    whatsapp_confirmation = make_confirmation(
        confirmation_id="confirmation-2",
        request=make_request(channel="whatsapp", integration=None),
    )

    repository.save_exclusive(web_confirmation)
    repository.save_exclusive(whatsapp_confirmation)

    web_loaded = repository.get("confirmation-1")
    whatsapp_loaded = repository.get("confirmation-2")

    assert web_loaded is not None
    assert web_loaded.revoked_at is None
    assert whatsapp_loaded is not None
    assert whatsapp_loaded.revoked_at is None


def test_save_exclusive_does_not_revoke_different_integration_binding(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    internal_confirmation = make_confirmation(
        confirmation_id="confirmation-1",
        request=make_request(channel="web", integration="internal"),
    )
    external_confirmation = make_confirmation(
        confirmation_id="confirmation-2",
        request=make_request(channel="web", integration="external"),
    )

    repository.save_exclusive(internal_confirmation)
    repository.save_exclusive(external_confirmation)

    internal_loaded = repository.get("confirmation-1")
    external_loaded = repository.get("confirmation-2")

    assert internal_loaded is not None
    assert internal_loaded.revoked_at is None
    assert external_loaded is not None
    assert external_loaded.revoked_at is None


def test_save_exclusive_replaces_expired_pending_confirmation(tmp_path):
    db = make_db(tmp_path)
    seed_business_and_user(db)
    repository = SQLiteCapabilityConfirmationRepository(db)

    expired = make_confirmation(
        confirmation_id="confirmation-1",
        request=make_request(channel="web", integration=None),
        created_at=NOW - timedelta(minutes=10),
        expires_at=NOW - timedelta(minutes=5),
    )
    replacement = make_confirmation(
        confirmation_id="confirmation-2",
        request=make_request(channel="web", integration=None),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    repository.save_exclusive(expired)
    repository.save_exclusive(replacement)

    expired_loaded = repository.get("confirmation-1")
    replacement_loaded = repository.get("confirmation-2")

    assert expired_loaded is not None
    assert expired_loaded.revoked_at is not None
    assert replacement_loaded is not None
    assert replacement_loaded.revoked_at is None
