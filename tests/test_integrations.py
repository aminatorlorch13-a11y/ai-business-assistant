from __future__ import annotations

import sqlite3

import pytest
from cryptography.fernet import Fernet

from app.integrations.security import FernetSecretCipher
from app.integrations.service import IntegrationService
from app.persistence.database import SQLiteDatabase
from app.persistence.integration_repository import SQLiteIntegrationRepository


@pytest.fixture
def integration_setup(tmp_path):
    database = SQLiteDatabase(tmp_path / "integrations.sqlite3")
    database.initialize()

    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    connection_id = service.connect(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        external_account_id="google-account-a",
        scopes={"email.read"},
        secret_payload={"access_token": "secret-token-value"},
        consent_confirmed=True,
    )

    return database, service, connection_id


def test_connection_requires_explicit_consent(integration_setup):
    _, service, _ = integration_setup

    with pytest.raises(PermissionError):
        service.connect(
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            external_account_id="google-account-b",
            scopes={"email.read"},
            secret_payload={"access_token": "another-secret"},
            consent_confirmed=False,
        )


def test_scope_is_tenant_scoped_and_explicit(integration_setup):
    _, service, connection_id = integration_setup

    assert service.has_permission(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
        scope="email.read",
    )

    assert not service.has_permission(
        connection_id=connection_id,
        business_id="business-b",
        user_id="user-a",
        scope="email.read",
    )

    assert not service.has_permission(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-b",
        scope="email.read",
    )

    assert not service.has_permission(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
        scope="email.send",
    )


def test_secret_is_encrypted_at_rest_and_can_be_read_by_owner(integration_setup):
    database, service, connection_id = integration_setup

    with database.connection() as db:
        row = db.execute(
            "SELECT encrypted_payload FROM integration_secrets "
            "WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()

    assert row is not None
    assert b"secret-token-value" not in bytes(row["encrypted_payload"])

    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    ) == {"access_token": "secret-token-value"}

    with pytest.raises(PermissionError):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-b",
            user_id="user-a",
        )


def test_revocation_removes_secret_and_disables_permission(integration_setup):
    database, service, connection_id = integration_setup

    service.revoke(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    )

    assert not service.has_permission(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
        scope="email.read",
    )

    with pytest.raises(PermissionError):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-a",
        )

    with database.connection() as db:
        secret_count = db.execute(
            "SELECT COUNT(*) FROM integration_secrets WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()[0]

    assert secret_count == 0


def test_audit_events_cannot_be_updated_or_deleted(integration_setup):
    database, _, _ = integration_setup

    with database.connection() as db:
        event = db.execute(
            "SELECT event_id FROM integration_audit_events LIMIT 1"
        ).fetchone()

        assert event is not None

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE integration_audit_events SET event_type = 'tampered' "
                "WHERE event_id = ?",
                (event["event_id"],),
            )

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "DELETE FROM integration_audit_events WHERE event_id = ?",
                (event["event_id"],),
            )


def test_unknown_or_unsupported_scopes_are_rejected(integration_setup):
    _, service, _ = integration_setup

    with pytest.raises(ValueError):
        service.connect(
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            external_account_id="google-account-c",
            scopes={"email.read", "gmail.delete_everything"},
            secret_payload={"access_token": "token"},
            consent_confirmed=True,
        )

    with pytest.raises(ValueError):
        service.connect(
            business_id="business-a",
            user_id="user-a",
            provider="unknown_provider",
            external_account_id="account-x",
            scopes={"anything"},
            secret_payload={"access_token": "token"},
            consent_confirmed=True,
        )


def test_connection_creation_rolls_back_everything_if_secret_insert_fails(tmp_path):
    database = SQLiteDatabase(tmp_path / "atomic-integrations.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    with database.transaction() as db:
        db.execute("""
            CREATE TRIGGER force_secret_insert_failure
            BEFORE INSERT ON integration_secrets
            BEGIN
                SELECT RAISE(ABORT, 'forced secret insert failure');
            END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="forced secret insert failure"):
        service.connect(
            business_id="business-atomic",
            user_id="user-atomic",
            provider="gmail",
            external_account_id="google-atomic",
            scopes={"email.read"},
            secret_payload={"access_token": "must-not-be-stored"},
            consent_confirmed=True,
        )

    with database.connection() as db:
        for table in (
            "integration_connections",
            "integration_permissions",
            "integration_secrets",
            "integration_audit_events",
        ):
            assert db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE business_id = ?",
                ("business-atomic",),
            ).fetchone()[0] == 0


def test_same_business_other_user_cannot_read_or_revoke_connection(integration_setup):
    database, service, connection_id = integration_setup

    with pytest.raises(PermissionError):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-b",
        )

    with pytest.raises(PermissionError):
        service.revoke(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-b",
        )

    assert service.has_permission(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
        scope="email.read",
    )
    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    ) == {"access_token": "secret-token-value"}

    with database.connection() as db:
        status = db.execute(
            "SELECT status FROM integration_connections WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()["status"]

    assert status == "active"


def test_unknown_secret_key_version_fails_closed(integration_setup):
    database, service, connection_id = integration_setup

    with database.transaction() as db:
        db.execute(
            "UPDATE integration_secrets SET key_version = ? "
            "WHERE connection_id = ?",
            ("unknown-key-v99", connection_id),
        )

    with pytest.raises(RuntimeError, match="unsupported key version"):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-a",
        )


def test_tampered_secret_ciphertext_is_rejected(integration_setup):
    database, service, connection_id = integration_setup

    with database.transaction() as db:
        row = db.execute(
            "SELECT encrypted_payload FROM integration_secrets "
            "WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()

        tampered = bytearray(row["encrypted_payload"])
        tampered[-2] = tampered[-2] ^ 1

        db.execute(
            "UPDATE integration_secrets SET encrypted_payload = ? "
            "WHERE connection_id = ?",
            (bytes(tampered), connection_id),
        )

    with pytest.raises(RuntimeError, match="could not be authenticated"):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-a",
        )


def test_old_secret_can_be_read_and_rotated_to_active_key(tmp_path):
    from app.integrations.security import FernetKeyringCipher

    database = SQLiteDatabase(tmp_path / "key-rotation.sqlite3")
    database.initialize()

    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    keyring = FernetKeyringCipher(
        keys={"fernet-v1": old_key, "fernet-v2": new_key},
        active_version="fernet-v2",
    )
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, keyring)

    connection_id = service.connect(
        business_id="business-rotation",
        user_id="user-rotation",
        provider="gmail",
        external_account_id="google-rotation",
        scopes={"email.read"},
        secret_payload={"access_token": "rotation-test-secret"},
        consent_confirmed=True,
    )

    old_cipher = FernetSecretCipher(old_key)
    old_ciphertext = old_cipher.encrypt(
        b'{"access_token":"rotation-test-secret"}'
    )
    repository.save_encrypted_secret(
        connection_id=connection_id,
        business_id="business-rotation",
        ciphertext=old_ciphertext,
        key_version="fernet-v1",
    )

    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-rotation",
        user_id="user-rotation",
    ) == {"access_token": "rotation-test-secret"}

    service.rotate_secret(
        connection_id=connection_id,
        business_id="business-rotation",
        user_id="user-rotation",
    )

    with database.connection() as db:
        row = db.execute(
            "SELECT encrypted_payload, key_version FROM integration_secrets "
            "WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()

    assert row["key_version"] == "fernet-v2"
    assert bytes(row["encrypted_payload"]) != old_ciphertext

    with database.connection() as db:
        audit = db.execute(
            "SELECT event_type, details_json FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'secret_rotated'",
            (connection_id,),
        ).fetchone()

    assert audit is not None
    assert '"old_key_version": "fernet-v1"' in audit["details_json"]
    assert '"new_key_version": "fernet-v2"' in audit["details_json"]
    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-rotation",
        user_id="user-rotation",
    ) == {"access_token": "rotation-test-secret"}


def test_rotation_rejects_stale_key_version(integration_setup):
    database, service, connection_id = integration_setup
    repository = service.repository
    cipher = service.cipher

    ciphertext, current_version = repository.get_encrypted_secret(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    )

    with pytest.raises(RuntimeError, match="changed during rotation"):
        repository.rotate_encrypted_secret(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-a",
            ciphertext=cipher.encrypt(b'{"access_token":"stale"}'),
            old_key_version="stale-version",
            new_key_version=current_version,
        )

    assert repository.get_encrypted_secret(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    ) == (ciphertext, current_version)


def test_permission_can_be_revoked_without_disconnecting_account(tmp_path):
    database = SQLiteDatabase(tmp_path / "permission-revocation.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    connection_id = service.connect(
        business_id="business-permissions",
        user_id="user-permissions",
        provider="gmail",
        external_account_id="google-permissions",
        scopes={"email.read", "email.send"},
        secret_payload={"access_token": "permission-test-secret"},
        consent_confirmed=True,
    )

    service.revoke_permission(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
        scope="email.send",
    )

    assert service.has_permission(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
        scope="email.read",
    )
    assert not service.has_permission(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
        scope="email.send",
    )

    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
    ) == {"access_token": "permission-test-secret"}

    with database.connection() as db:
        event = db.execute(
            "SELECT details_json FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'permission_revoked'",
            (connection_id,),
        ).fetchone()

    assert event is not None
    assert '"scope": "email.send"' in event["details_json"]


def test_other_user_cannot_revoke_connection_permission(tmp_path):
    database = SQLiteDatabase(tmp_path / "permission-owner.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    connection_id = service.connect(
        business_id="shared-business",
        user_id="connection-owner",
        provider="gmail",
        external_account_id="google-owner",
        scopes={"email.read", "email.send"},
        secret_payload={"access_token": "owner-secret"},
        consent_confirmed=True,
    )

    with pytest.raises(PermissionError):
        service.revoke_permission(
            connection_id=connection_id,
            business_id="shared-business",
            user_id="different-user",
            scope="email.send",
        )

    assert service.has_permission(
        connection_id=connection_id,
        business_id="shared-business",
        user_id="connection-owner",
        scope="email.send",
    )

    with database.connection() as db:
        events = db.execute(
            "SELECT COUNT(*) FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'permission_revoked'",
            (connection_id,),
        ).fetchone()[0]

    assert events == 0


def test_permission_cannot_be_revoked_twice(tmp_path):
    database = SQLiteDatabase(tmp_path / "repeat-revoke.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    connection_id = service.connect(
        business_id="repeat-business",
        user_id="repeat-user",
        provider="gmail",
        external_account_id="google-repeat",
        scopes={"email.read"},
        secret_payload={"access_token": "repeat-secret"},
        consent_confirmed=True,
    )

    arguments = {
        "connection_id": connection_id,
        "business_id": "repeat-business",
        "user_id": "repeat-user",
        "scope": "email.read",
    }

    service.revoke_permission(**arguments)

    with pytest.raises(PermissionError):
        service.revoke_permission(**arguments)

    with database.connection() as db:
        events = db.execute(
            "SELECT COUNT(*) FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'permission_revoked'",
            (connection_id,),
        ).fetchone()[0]

    assert events == 1


def test_integration_schema_has_no_foreign_key_violations(tmp_path):
    database = SQLiteDatabase(tmp_path / "foreign-keys.sqlite3")
    database.initialize()

    with database.connection() as db:
        violations = db.execute("PRAGMA foreign_key_check").fetchall()

    assert violations == []


def test_oauth_attempt_requires_explicit_consent(integration_setup):
    _, service, _ = integration_setup

    with pytest.raises(PermissionError):
        service.create_oauth_attempt(
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
            consent_confirmed=False,
        )


def test_oauth_attempt_is_single_use_and_returns_pkce_verifier(integration_setup):
    database, service, _ = integration_setup

    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
    )

    assert attempt["code_challenge_method"] == "S256"
    assert len(attempt["code_challenge"]) == 43

    with database.connection() as db:
        stored = db.execute(
            "SELECT state_hash, encrypted_code_verifier "
            "FROM oauth_authorization_attempts"
        ).fetchone()

    assert stored is not None
    assert stored["state_hash"] != attempt["state"]
    assert attempt["state"] not in stored["state_hash"]
    assert stored["encrypted_code_verifier"] != attempt["state"].encode()

    result = service.consume_oauth_attempt(
        state=attempt["state"],
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
    )

    assert len(result["code_verifier"]) >= 43
    assert result["provider"] == "gmail"

    with pytest.raises(PermissionError):
        service.consume_oauth_attempt(
            state=attempt["state"],
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
        )


def test_oauth_attempt_rejects_wrong_tenant_provider_and_redirect(integration_setup):
    _, service, _ = integration_setup

    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
    )

    invalid_contexts = (
        ("business-other", "user-a", "gmail", "https://example.com/oauth/callback"),
        ("business-a", "user-other", "gmail", "https://example.com/oauth/callback"),
        ("business-a", "user-a", "telegram", "https://example.com/oauth/callback"),
        ("business-a", "user-a", "gmail", "https://attacker.example/callback"),
    )

    for business_id, user_id, provider, redirect_uri in invalid_contexts:
        with pytest.raises(PermissionError):
            service.consume_oauth_attempt(
                state=attempt["state"],
                business_id=business_id,
                user_id=user_id,
                provider=provider,
                redirect_uri=redirect_uri,
            )

    # A failed context check must not consume the legitimate attempt.
    result = service.consume_oauth_attempt(
        state=attempt["state"],
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
    )
    assert result["provider"] == "gmail"


def test_oauth_attempt_rejects_expired_state(integration_setup):
    _, service, _ = integration_setup

    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
        ttl_seconds=60,
    )

    # Move the stored expiry into the past to test expiry deterministically.
    with service.repository.database.transaction() as db:
        db.execute(
            "UPDATE oauth_authorization_attempts "
            "SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE state_hash = ?",
            (__import__("hashlib").sha256(
                attempt["state"].encode("utf-8")
            ).hexdigest(),),
        )

    with pytest.raises(PermissionError):
        service.consume_oauth_attempt(
            state=attempt["state"],
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
        )


def test_oauth_attempt_rejects_insecure_redirect_uri(integration_setup):
    _, service, _ = integration_setup

    with pytest.raises(ValueError):
        service.create_oauth_attempt(
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="http://example.com/callback",
            consent_confirmed=True,
        )

def test_oauth_pkce_challenge_matches_verifier(integration_setup):
    import base64
    import hashlib

    _, service, _ = integration_setup
    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
    )
    result = service.consume_oauth_attempt(
        state=attempt["state"],
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
    )

    expected = base64.urlsafe_b64encode(
        hashlib.sha256(result["code_verifier"].encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    assert attempt["code_challenge_method"] == "S256"
    assert attempt["code_challenge"] == expected


def test_oauth_verifier_decrypts_with_historical_key(integration_setup):
    from cryptography.fernet import Fernet
    from app.integrations.security import FernetKeyringCipher

    _, service, _ = integration_setup
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()

    service.cipher = FernetKeyringCipher({"old": old_key}, "old")
    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
    )

    service.cipher = FernetKeyringCipher(
        {"old": old_key, "new": new_key}, "new"
    )
    result = service.consume_oauth_attempt(
        state=attempt["state"],
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
    )

    assert result["code_verifier"]
    assert result["provider"] == "gmail"


def test_oauth_tampered_verifier_fails_closed(integration_setup):
    import hashlib

    _, service, _ = integration_setup
    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
    )
    state_hash = hashlib.sha256(
        attempt["state"].encode("utf-8")
    ).hexdigest()

    with service.repository.database.transaction() as db:
        row = db.execute(
            "SELECT encrypted_code_verifier FROM oauth_authorization_attempts "
            "WHERE state_hash = ?",
            (state_hash,),
        ).fetchone()
        assert row is not None
        tampered = bytes(row["encrypted_code_verifier"]) + b"x"
        db.execute(
            "UPDATE oauth_authorization_attempts "
            "SET encrypted_code_verifier = ? WHERE state_hash = ?",
            (tampered, state_hash),
        )

    with pytest.raises(RuntimeError):
        service.consume_oauth_attempt(
            state=attempt["state"],
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
        )

    with pytest.raises(PermissionError):
        service.consume_oauth_attempt(
            state=attempt["state"],
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
        )

