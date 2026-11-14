from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
import json

from app.persistence.database import SQLiteDatabase
from app.integrations.models import IntegrationConnection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{field} must be a non-empty string of at most 256 characters.")
    return value.strip()


class SQLiteIntegrationRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create_oauth_attempt(
        self, *, state_hash: str, business_id: str, user_id: str,
        provider: str, redirect_uri: str,
        encrypted_code_verifier: bytes, key_version: str,
        created_at: str, expires_at: str,
    ) -> None:
        values = (
            _required(state_hash, "state_hash"),
            _required(business_id, "business_id"),
            _required(user_id, "user_id"),
            _required(provider, "provider"),
            _required(redirect_uri, "redirect_uri"),
            encrypted_code_verifier,
            _required(key_version, "key_version"),
            _required(created_at, "created_at"),
            _required(expires_at, "expires_at"),
        )

        if not isinstance(encrypted_code_verifier, bytes) or not encrypted_code_verifier:
            raise ValueError("Encrypted PKCE verifier is required.")

        if expires_at <= created_at:
            raise ValueError("OAuth attempt expiry must be after creation.")

        with self.database.transaction() as db:
            db.execute("""
                INSERT INTO oauth_authorization_attempts(
                    state_hash, business_id, user_id, provider,
                    redirect_uri, encrypted_code_verifier, key_version,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)

    def consume_oauth_attempt(
        self, *, state_hash: str, business_id: str, user_id: str,
        provider: str, redirect_uri: str, now: str,
    ) -> dict[str, object]:
        with self.database.transaction() as db:
            row = db.execute("""
                SELECT state_hash, business_id, user_id, provider,
                       redirect_uri, encrypted_code_verifier, key_version,
                       created_at, expires_at, consumed_at
                FROM oauth_authorization_attempts
                WHERE state_hash = ?
                  AND business_id = ?
                  AND user_id = ?
                  AND provider = ?
                  AND redirect_uri = ?
            """, (
                state_hash, business_id, user_id, provider,
                redirect_uri,
            )).fetchone()

            if row is None:
                raise PermissionError("OAuth authorisation attempt is invalid.")

            if row["consumed_at"] is not None:
                raise PermissionError("OAuth authorisation attempt was already used.")

            if row["expires_at"] <= now:
                raise PermissionError("OAuth authorisation attempt has expired.")

            updated = db.execute("""
                UPDATE oauth_authorization_attempts
                SET consumed_at = ?
                WHERE state_hash = ? AND consumed_at IS NULL
                  AND expires_at > ?
            """, (now, state_hash, now))

            if updated.rowcount != 1:
                raise PermissionError("OAuth authorisation attempt is no longer valid.")

            return dict(row)


    def create_connection(
        self, *, connection_id: str, business_id: str, user_id: str,
        provider: str, external_account_id: str, scopes: set[str],
    ) -> None:
        values = (
            _required(connection_id, "connection_id"),
            _required(business_id, "business_id"),
            _required(user_id, "user_id"),
            _required(provider, "provider"),
            _required(external_account_id, "external_account_id"),
        )
        timestamp = _now()
        with self.database.transaction() as db:
            db.execute("""
                INSERT INTO integration_connections(
                    connection_id, business_id, user_id, provider,
                    external_account_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?)
            """, (*values, timestamp))
            for scope in sorted(scopes):
                db.execute("""
                    INSERT INTO integration_permissions(
                        permission_id, connection_id, business_id, user_id,
                        scope, granted_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (str(uuid4()), values[0], values[1], values[2], scope, timestamp))
            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'connection_created', ?, ?)
            """, (str(uuid4()), values[1], values[2], values[0], timestamp,
                  json.dumps({"provider": values[3], "scopes": sorted(scopes)})))

    def create_connection_with_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
        provider: str, external_account_id: str, scopes: set[str],
        ciphertext: bytes, key_version: str,
    ) -> None:
        values = (
            _required(connection_id, "connection_id"),
            _required(business_id, "business_id"),
            _required(user_id, "user_id"),
            _required(provider, "provider"),
            _required(external_account_id, "external_account_id"),
        )
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted secret is required.")
        version = _required(key_version, "key_version")
        timestamp = _now()

        with self.database.transaction() as db:
            db.execute("""
                INSERT INTO integration_connections(
                    connection_id, business_id, user_id, provider,
                    external_account_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?)
            """, (*values, timestamp))

            for scope in sorted(scopes):
                db.execute("""
                    INSERT INTO integration_permissions(
                        permission_id, connection_id, business_id, user_id,
                        scope, granted_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid4()), values[0], values[1], values[2],
                    scope, timestamp,
                ))

            db.execute("""
                INSERT INTO integration_secrets(
                    connection_id, business_id, encrypted_payload,
                    key_version, updated_at
                ) VALUES (?, ?, ?, ?, ?)
            """, (values[0], values[1], ciphertext, version, timestamp))

            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'connection_created', ?, ?)
            """, (
                str(uuid4()), values[1], values[2], values[0], timestamp,
                json.dumps({"provider": values[3], "scopes": sorted(scopes)}),
            ))

    def save_encrypted_secret(
        self, *, connection_id: str, business_id: str,
        ciphertext: bytes, key_version: str,
    ) -> None:
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted secret is required.")
        with self.database.transaction() as db:
            active = db.execute("""
                SELECT 1 FROM integration_connections
                WHERE connection_id = ? AND business_id = ? AND status = 'active'
            """, (connection_id, business_id)).fetchone()
            if active is None:
                raise PermissionError("Active tenant-owned integration required.")
            db.execute("""
                INSERT INTO integration_secrets(
                    connection_id, business_id, encrypted_payload,
                    key_version, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    encrypted_payload = excluded.encrypted_payload,
                    key_version = excluded.key_version,
                    updated_at = excluded.updated_at
            """, (connection_id, business_id, ciphertext, key_version, _now()))

    def get_encrypted_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> tuple[bytes, str]:
        with self.database.connection() as db:
            row = db.execute("""
                SELECT s.encrypted_payload, s.key_version
                FROM integration_secrets s
                JOIN integration_connections c
                  ON c.connection_id = s.connection_id
                 AND c.business_id = s.business_id
                WHERE s.connection_id = ? AND s.business_id = ?
                  AND c.user_id = ? AND c.status = 'active'
            """, (connection_id, business_id, user_id)).fetchone()
        if row is None:
            raise PermissionError("Active tenant-owned integration secret not found.")
        return bytes(row["encrypted_payload"]), str(row["key_version"])

    def has_permission(
        self, *, connection_id: str, business_id: str,
        user_id: str, scope: str,
    ) -> bool:
        with self.database.connection() as db:
            row = db.execute("""
                SELECT 1
                FROM integration_permissions p
                JOIN integration_connections c
                  ON c.connection_id = p.connection_id
                 AND c.business_id = p.business_id
                 AND c.user_id = p.user_id
                WHERE p.connection_id = ? AND p.business_id = ?
                  AND p.user_id = ? AND p.scope = ?
                  AND p.revoked_at IS NULL AND c.status = 'active'
            """, (connection_id, business_id, user_id, scope)).fetchone()
        return row is not None

    def revoke_permission(
        self, *, connection_id: str, business_id: str, user_id: str,
        scope: str,
    ) -> None:
        permission_scope = _required(scope, "scope")
        timestamp = _now()

        with self.database.transaction() as db:
            connection = db.execute("""
                SELECT provider FROM integration_connections
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND status = 'active'
            """, (connection_id, business_id, user_id)).fetchone()

            if connection is None:
                raise PermissionError("Active tenant-owned connection not found.")

            updated = db.execute("""
                UPDATE integration_permissions
                SET revoked_at = ?
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND scope = ? AND revoked_at IS NULL
            """, (
                timestamp, connection_id, business_id, user_id,
                permission_scope,
            ))

            if updated.rowcount != 1:
                raise PermissionError("Active permission not found.")

            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'permission_revoked', ?, ?)
            """, (
                str(uuid4()), business_id, user_id, connection_id, timestamp,
                json.dumps({
                    "provider": connection["provider"],
                    "scope": permission_scope,
                }),
            ))

    def revoke_connection(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> None:
        timestamp = _now()
        with self.database.transaction() as db:
            row = db.execute("""
                SELECT provider FROM integration_connections
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND status = 'active'
            """, (connection_id, business_id, user_id)).fetchone()
            if row is None:
                raise PermissionError("Active tenant-owned connection not found.")
            db.execute("""
                UPDATE integration_connections
                SET status = 'revoked', revoked_at = ?
                WHERE connection_id = ? AND business_id = ? AND user_id = ?
            """, (timestamp, connection_id, business_id, user_id))
            db.execute("""
                UPDATE integration_permissions SET revoked_at = ?
                WHERE connection_id = ? AND business_id = ? AND user_id = ?
                  AND revoked_at IS NULL
            """, (timestamp, connection_id, business_id, user_id))
            db.execute("""
                DELETE FROM integration_secrets
                WHERE connection_id = ? AND business_id = ?
            """, (connection_id, business_id))
            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'connection_revoked', ?, ?)
            """, (str(uuid4()), business_id, user_id, connection_id, timestamp,
                  json.dumps({"provider": row["provider"], "secrets_deleted": True})))

    def replace_oauth_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
        expected_ciphertext: bytes, expected_key_version: str,
        ciphertext: bytes, key_version: str,
    ) -> None:
        """Atomically replace Gmail OAuth credentials and audit the refresh."""
        if not isinstance(expected_ciphertext, bytes) or not expected_ciphertext:
            raise ValueError("Expected encrypted secret is required.")
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted replacement secret is required.")

        old_version = _required(expected_key_version, "expected_key_version")
        new_version = _required(key_version, "key_version")
        timestamp = _now()

        with self.database.transaction() as db:
            owner = db.execute("""
                SELECT provider FROM integration_connections
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND status = 'active'
            """, (connection_id, business_id, user_id)).fetchone()

            if owner is None or owner["provider"] != "gmail":
                raise PermissionError("Active Gmail connection not found.")

            updated = db.execute("""
                UPDATE integration_secrets
                SET encrypted_payload = ?, key_version = ?, updated_at = ?
                WHERE connection_id = ? AND business_id = ?
                  AND encrypted_payload = ? AND key_version = ?
            """, (
                ciphertext, new_version, timestamp,
                connection_id, business_id, expected_ciphertext, old_version,
            ))

            if updated.rowcount != 1:
                raise RuntimeError(
                    "Gmail credentials changed during refresh; reload before retrying."
                )

            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'oauth_token_refreshed', ?, ?)
            """, (
                str(uuid4()), business_id, user_id, connection_id, timestamp,
                json.dumps({
                    "provider": "gmail",
                    "key_version": new_version,
                }),
            ))

    def rotate_encrypted_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
        ciphertext: bytes, old_key_version: str, new_key_version: str,
    ) -> None:
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted secret is required.")
        old_version = _required(old_key_version, "old_key_version")
        new_version = _required(new_key_version, "new_key_version")
        timestamp = _now()

        with self.database.transaction() as db:
            owner = db.execute("""
                SELECT provider FROM integration_connections
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND status = 'active'
            """, (connection_id, business_id, user_id)).fetchone()

            if owner is None:
                raise PermissionError("Active tenant-owned connection not found.")

            updated = db.execute("""
                UPDATE integration_secrets
                SET encrypted_payload = ?, key_version = ?, updated_at = ?
                WHERE connection_id = ? AND business_id = ?
                  AND key_version = ?
            """, (
                ciphertext, new_version, timestamp,
                connection_id, business_id, old_version,
            ))

            if updated.rowcount != 1:
                raise RuntimeError(
                    "Secret changed during rotation; reload it before retrying."
                )

            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'secret_rotated', ?, ?)
            """, (
                str(uuid4()), business_id, user_id, connection_id, timestamp,
                json.dumps({
                    "provider": owner["provider"],
                    "old_key_version": old_version,
                    "new_key_version": new_version,
                }),
            ))

    def list_active_connections(
        self, *, provider: str, business_id: str, user_id: str, scope: str,
    ) -> list[IntegrationConnection]:
        """List active tenant-owned connections with an active permission."""
        with self.database.connection() as db:
            rows = db.execute("""
                SELECT DISTINCT c.*
                FROM integration_connections c
                JOIN integration_permissions p
                  ON p.connection_id = c.connection_id
                 AND p.business_id = c.business_id
                 AND p.user_id = c.user_id
                WHERE c.provider = ?
                  AND c.business_id = ?
                  AND c.user_id = ?
                  AND c.status = 'active'
                  AND p.scope = ?
                  AND p.revoked_at IS NULL
                ORDER BY c.created_at DESC, c.connection_id ASC
            """, (provider, business_id, user_id, scope)).fetchall()

        parse = lambda value: datetime.fromisoformat(value) if value else None
        return [
            IntegrationConnection(
                connection_id=row["connection_id"],
                business_id=row["business_id"],
                user_id=row["user_id"],
                provider=row["provider"],
                external_account_id=row["external_account_id"],
                status=row["status"],
                created_at=parse(row["created_at"]),
                revoked_at=parse(row["revoked_at"]),
            )
            for row in rows
        ]

    def get_connection(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> IntegrationConnection:
        with self.database.connection() as db:
            row = db.execute("""
                SELECT * FROM integration_connections
                WHERE connection_id = ? AND business_id = ? AND user_id = ?
            """, (connection_id, business_id, user_id)).fetchone()
        if row is None:
            raise PermissionError("Tenant-owned integration connection not found.")
        parse = lambda value: datetime.fromisoformat(value) if value else None
        return IntegrationConnection(
            connection_id=row["connection_id"],
            business_id=row["business_id"],
            user_id=row["user_id"],
            provider=row["provider"],
            external_account_id=row["external_account_id"],
            status=row["status"],
            created_at=parse(row["created_at"]),
            revoked_at=parse(row["revoked_at"]),
        )
