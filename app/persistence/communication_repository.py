from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4
import re

from app.persistence.database import SQLiteDatabase


CHANNELS = {"whatsapp", "sms", "email", "voice", "companion_app"}
DELIVERY_STATES = {
    "sent", "delivered", "failed", "unknown", "acknowledged", "cancelled"
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: str, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters.")
    return value.strip()


class SQLiteCommunicationRepository:
    """Tenant-scoped persistence for authorised communication and delivery."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        with self.database.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS owner_endpoint_verification_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    provider_account_id TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL,
                    encrypted_endpoint BLOB NOT NULL,
                    key_version TEXT NOT NULL,
                    endpoint_fingerprint TEXT NOT NULL,
                    proof_digest TEXT NOT NULL,
                    consent_granted INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL,
                    CHECK (channel IN ('whatsapp', 'sms', 'email', 'voice', 'companion_app')),
                    CHECK (attempts >= 0),
                    CHECK (max_attempts >= 1)
                )
            """)
            columns = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(owner_endpoint_verification_challenges)"
                ).fetchall()
            }
            if "provider_account_id" not in columns:
                db.execute("""
                    ALTER TABLE owner_endpoint_verification_challenges
                    ADD COLUMN provider_account_id TEXT NOT NULL DEFAULT ''
                """)
            if "consent_granted" not in columns:
                db.execute("""
                    ALTER TABLE owner_endpoint_verification_challenges
                    ADD COLUMN consent_granted INTEGER NOT NULL DEFAULT 0
                """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_endpoint_challenges_provider
                ON owner_endpoint_verification_challenges(
                    provider_account_id, endpoint_fingerprint, expires_at
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_endpoint_challenges_pending
                ON owner_endpoint_verification_challenges(
                    business_id, user_id, channel, endpoint_fingerprint,
                    expires_at
                )
            """)

    def register_endpoint(
        self, *, endpoint_id: str, business_id: str, user_id: str,
        channel: str, encrypted_endpoint: bytes, key_version: str,
        fingerprint: str, verified_at: str, consent_granted_at: str,
    ) -> None:
        endpoint_id = _required(endpoint_id, "endpoint_id")
        business_id = _required(business_id, "business_id")
        user_id = _required(user_id, "user_id")
        if channel not in CHANNELS:
            raise ValueError("Unsupported communication channel.")
        if not isinstance(encrypted_endpoint, bytes) or not encrypted_endpoint:
            raise ValueError("Encrypted endpoint is required.")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("A SHA-256 endpoint fingerprint is required.")
        key_version = _required(key_version, "key_version")
        verified_at = _required(verified_at, "verified_at")
        consent_granted_at = _required(consent_granted_at, "consent_granted_at")
        now = _now()

        with self.database.transaction() as db:
            db.execute("""
                INSERT INTO owner_communication_channels(
                    endpoint_id, business_id, user_id, channel,
                    encrypted_endpoint, key_version, endpoint_fingerprint,
                    verified_at, consent_granted_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                endpoint_id, business_id, user_id, channel,
                encrypted_endpoint, key_version, fingerprint,
                verified_at, consent_granted_at, now, now,
            ))

    def list_enabled_endpoints(
        self, *, business_id: str, user_id: str,
    ) -> list[dict[str, object]]:
        with self.database.connection() as db:
            rows = db.execute("""
                SELECT endpoint_id, channel, encrypted_endpoint, key_version,
                       verified_at, consent_granted_at
                FROM owner_communication_channels
                WHERE business_id = ? AND user_id = ?
                  AND revoked_at IS NULL
                  AND verified_at IS NOT NULL
                  AND consent_granted_at IS NOT NULL
                ORDER BY created_at
            """, (business_id, user_id)).fetchall()
        return [dict(row) for row in rows]

    def revoke_endpoint(
        self, *, endpoint_id: str, business_id: str, user_id: str,
    ) -> bool:
        with self.database.transaction() as db:
            result = db.execute("""
                UPDATE owner_communication_channels
                SET revoked_at = ?, updated_at = ?
                WHERE endpoint_id = ? AND business_id = ? AND user_id = ?
                  AND revoked_at IS NULL
            """, (_now(), _now(), endpoint_id, business_id, user_id))
            return result.rowcount == 1

    def save_tenant_identity(
        self, *, business_id: str, provider: str,
        encrypted_identity: bytes, key_version: str,
        status: str, provisioned_at: str | None = None,
    ) -> None:
        business_id = _required(business_id, "business_id")
        provider = _required(provider, "provider")
        key_version = _required(key_version, "key_version")
        if not isinstance(encrypted_identity, bytes) or not encrypted_identity:
            raise ValueError("Encrypted provider-assigned identity is required.")
        if status not in {"pending", "active", "suspended", "released"}:
            raise ValueError("Invalid tenant communication identity status.")
        if status == "active" and not provisioned_at:
            raise ValueError("An active identity requires provider-confirmed provisioning.")
        now = _now()

        with self.database.transaction() as db:
            db.execute("""
                INSERT INTO tenant_communication_identities(
                    business_id, provider, encrypted_identity, key_version,
                    status, provisioned_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_id) DO UPDATE SET
                    provider = excluded.provider,
                    encrypted_identity = excluded.encrypted_identity,
                    key_version = excluded.key_version,
                    status = excluded.status,
                    provisioned_at = excluded.provisioned_at,
                    updated_at = excluded.updated_at
            """, (
                business_id, provider, encrypted_identity, key_version,
                status, provisioned_at, now, now,
            ))

    def get_tenant_identity(self, *, business_id: str) -> dict[str, object] | None:
        with self.database.connection() as db:
            row = db.execute("""
                SELECT provider, encrypted_identity, key_version,
                       status, provisioned_at
                FROM tenant_communication_identities
                WHERE business_id = ?
            """, (business_id,)).fetchone()
        return dict(row) if row else None

    def queue_delivery(
        self, *, event_id: str, business_id: str, user_id: str,
        endpoint_ids: list[str], max_attempts: int = 3,
        next_attempt_at: str | None = None,
    ) -> int:
        if not endpoint_ids:
            return 0
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer.")
        if len(set(endpoint_ids)) != len(endpoint_ids):
            raise ValueError("Duplicate endpoint IDs are not allowed.")

        now = _now()
        scheduled = next_attempt_at or now
        created = 0

        with self.database.transaction() as db:
            event = db.execute("""
                SELECT 1 FROM attention_events
                WHERE event_id = ? AND business_id = ? AND user_id = ?
            """, (event_id, business_id, user_id)).fetchone()
            if event is None:
                raise PermissionError("Tenant-owned attention event not found.")

            for endpoint_id in endpoint_ids:
                endpoint = db.execute("""
                    SELECT channel FROM owner_communication_channels
                    WHERE endpoint_id = ? AND business_id = ? AND user_id = ?
                      AND revoked_at IS NULL
                      AND verified_at IS NOT NULL
                      AND consent_granted_at IS NOT NULL
                """, (endpoint_id, business_id, user_id)).fetchone()
                if endpoint is None:
                    continue

                result = db.execute("""
                    INSERT OR IGNORE INTO attention_delivery_attempts(
                        delivery_id, event_id, business_id, user_id,
                        endpoint_id, channel, status, attempts, max_attempts,
                        next_attempt_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)
                """, (
                    str(uuid4()), event_id, business_id, user_id,
                    endpoint_id, endpoint["channel"], max_attempts,
                    scheduled, now, now,
                ))
                created += result.rowcount
        return created

    def claim_due_attempts(
        self, *, business_id: str, user_id: str, worker_id: str,
        limit: int = 10, lease_seconds: int = 60,
        now: str | None = None,
    ) -> list[dict[str, object]]:
        worker_id = _required(worker_id, "worker_id")
        if not 1 <= limit <= 100 or not 5 <= lease_seconds <= 900:
            raise ValueError("Invalid claim limit or lease duration.")
        timestamp = now or _now()
        lease_until = (
            datetime.fromisoformat(timestamp) + timedelta(seconds=lease_seconds)
        ).isoformat()
        claimed: list[dict[str, object]] = []

        with self.database.transaction() as db:
            rows = db.execute("""
                SELECT d.delivery_id
                FROM attention_delivery_attempts d
                JOIN owner_communication_channels c
                  ON c.endpoint_id = d.endpoint_id
                WHERE d.business_id = ? AND d.user_id = ?
                  AND d.status = 'queued'
                  AND d.attempts < d.max_attempts
                  AND d.next_attempt_at <= ?
                  AND c.revoked_at IS NULL
                  AND c.verified_at IS NOT NULL
                  AND c.consent_granted_at IS NOT NULL
                ORDER BY d.next_attempt_at, d.created_at
                LIMIT ?
            """, (business_id, user_id, timestamp, limit)).fetchall()

            for row in rows:
                token = str(uuid4())
                updated = db.execute("""
                    UPDATE attention_delivery_attempts
                    SET status = 'claimed', attempts = attempts + 1,
                        claim_token = ?, lease_expires_at = ?, claimed_by = ?,
                        last_attempt_at = ?, updated_at = ?
                    WHERE delivery_id = ? AND status = 'queued'
                """, (token, lease_until, worker_id, timestamp, timestamp, row["delivery_id"]))
                if updated.rowcount != 1:
                    continue
                item = db.execute("""
                    SELECT * FROM attention_delivery_attempts
                    WHERE delivery_id = ?
                """, (row["delivery_id"],)).fetchone()
                claimed.append(dict(item))
        return claimed

    def finish_attempt(
        self, *, delivery_id: str, claim_token: str, outcome: str,
        provider_reference: str | None = None,
        failure_reason: str | None = None,
        retry_at: str | None = None,
    ) -> bool:
        if outcome not in DELIVERY_STATES:
            raise ValueError("Unsupported delivery outcome.")
        now = _now()

        with self.database.transaction() as db:
            row = db.execute("""
                SELECT attempts, max_attempts, lease_expires_at
                FROM attention_delivery_attempts
                WHERE delivery_id = ? AND status = 'claimed'
                  AND claim_token = ?
            """, (delivery_id, claim_token)).fetchone()
            if row is None or row["lease_expires_at"] <= now:
                return False

            next_status = outcome
            next_attempt = None
            if outcome == "failed" and retry_at and row["attempts"] < row["max_attempts"]:
                next_status = "queued"
                next_attempt = retry_at

            result = db.execute("""
                UPDATE attention_delivery_attempts
                SET status = ?, next_attempt_at = ?,
                    provider_reference = ?, failure_reason = ?,
                    delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END,
                    acknowledged_at = CASE WHEN ? = 'acknowledged' THEN ? ELSE acknowledged_at END,
                    claim_token = NULL, lease_expires_at = NULL,
                    claimed_by = NULL, updated_at = ?
                WHERE delivery_id = ? AND status = 'claimed' AND claim_token = ?
            """, (
                next_status, next_attempt, provider_reference, failure_reason,
                outcome, now, outcome, now, now, delivery_id, claim_token,
            ))
            return result.rowcount == 1

    def recover_expired_claims(
        self, *, business_id: str, user_id: str,
        now: str | None = None, limit: int = 100,
    ) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("Recovery limit must be between 1 and 1000.")

        timestamp = now or _now()
        with self.database.transaction() as db:
            rows = db.execute("""
                SELECT delivery_id
                FROM attention_delivery_attempts
                WHERE business_id = ? AND user_id = ?
                  AND status = 'claimed'
                  AND lease_expires_at <= ?
                ORDER BY lease_expires_at, created_at
                LIMIT ?
            """, (business_id, user_id, timestamp, limit)).fetchall()

            recovered = 0
            for row in rows:
                result = db.execute("""
                    UPDATE attention_delivery_attempts
                    SET status = 'unknown',
                        failure_reason = 'claim_expired_outcome_unknown',
                        claim_token = NULL,
                        lease_expires_at = NULL,
                        claimed_by = NULL,
                        updated_at = ?
                    WHERE delivery_id = ?
                      AND business_id = ? AND user_id = ?
                      AND status = 'claimed'
                      AND lease_expires_at <= ?
                """, (
                    timestamp, row["delivery_id"],
                    business_id, user_id, timestamp,
                ))
                recovered += result.rowcount
            return recovered

    def acknowledge_attempt(
        self, *, delivery_id: str, business_id: str, user_id: str,
    ) -> bool:
        now = _now()
        with self.database.transaction() as db:
            result = db.execute("""
                UPDATE attention_delivery_attempts
                SET status = 'acknowledged', acknowledged_at = ?,
                    claim_token = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE delivery_id = ? AND business_id = ? AND user_id = ?
                  AND status IN ('sent', 'delivered')
            """, (now, now, delivery_id, business_id, user_id))
            return result.rowcount == 1

    def create_endpoint_challenge(
        self, *,
        challenge_id: str,
        business_id: str,
        user_id: str,
        channel: str,
        encrypted_endpoint: bytes,
        provider_account_id: str | None = None,
        consent_granted: bool = False,
        key_version: str,
        fingerprint: str,
        proof_digest: str,
        expires_at: str,
        max_attempts: int = 5,
    ) -> None:
        challenge_id = _required(challenge_id, "challenge_id")
        business_id = _required(business_id, "business_id")
        user_id = _required(user_id, "user_id")
        key_version = _required(key_version, "key_version")
        expires_at = _required(expires_at, "expires_at")
        provider_account_id = (provider_account_id or "").strip()

        if channel == "whatsapp" and not provider_account_id:
            raise ValueError("A Meta provider account ID is required for WhatsApp.")
        if consent_granted is not True:
            raise ValueError("Explicit communication consent is required.")

        if channel not in CHANNELS:
            raise ValueError("Unsupported communication channel.")
        if not isinstance(encrypted_endpoint, bytes) or not encrypted_endpoint:
            raise ValueError("Encrypted endpoint is required.")
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint or ""):
            raise ValueError("A SHA-256 endpoint fingerprint is required.")
        if not re.fullmatch(r"[a-f0-9]{64}", proof_digest or ""):
            raise ValueError("A SHA-256 proof digest is required.")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 10
        ):
            raise ValueError("max_attempts must be between 1 and 10.")

        now = _now()
        with self.database.transaction() as db:
            # A new challenge invalidates older pending challenges for this
            # exact endpoint and tenant. Only one active code is accepted.
            db.execute("""
                UPDATE owner_endpoint_verification_challenges
                SET consumed_at = ?
                WHERE business_id = ? AND user_id = ?
                  AND channel = ? AND endpoint_fingerprint = ?
                  AND consumed_at IS NULL
            """, (now, business_id, user_id, channel, fingerprint))

            db.execute("""
                INSERT INTO owner_endpoint_verification_challenges(
                    challenge_id, business_id, user_id, provider_account_id,
                    channel, encrypted_endpoint, key_version,
                    endpoint_fingerprint, proof_digest, consent_granted,
                    expires_at, attempts, max_attempts, consumed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?)
            """, (
                challenge_id, business_id, user_id, provider_account_id,
                channel, encrypted_endpoint, key_version, fingerprint,
                proof_digest, int(consent_granted), expires_at,
                max_attempts, now,
            ))

    def confirm_endpoint_challenge(
        self, *,
        challenge_id: str,
        proof_digest: str,
        endpoint_id: str,
        provider_account_id: str,
        fingerprint: str,
        now: str | None = None,
    ) -> bool:
        challenge_id = _required(challenge_id, "challenge_id")
        endpoint_id = _required(endpoint_id, "endpoint_id")
        provider_account_id = _required(provider_account_id, "provider_account_id")
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint or ""):
            raise ValueError("A SHA-256 endpoint fingerprint is required.")
        if not re.fullmatch(r"[a-f0-9]{64}", proof_digest or ""):
            raise ValueError("A SHA-256 proof digest is required.")

        timestamp = now or _now()

        with self.database.transaction() as db:
            row = db.execute("""
                SELECT *
                FROM owner_endpoint_verification_challenges
                WHERE challenge_id = ?
            """, (challenge_id,)).fetchone()

            if row is None or row["consumed_at"] is not None:
                return False

            # The challenge must belong to this exact sender and Meta
            # business phone-number account.
            if (
                row["provider_account_id"] != provider_account_id
                or row["endpoint_fingerprint"] != fingerprint
            ):
                return False

            if row["expires_at"] <= timestamp:
                db.execute("""
                    UPDATE owner_endpoint_verification_challenges
                    SET consumed_at = ?
                    WHERE challenge_id = ? AND consumed_at IS NULL
                """, (timestamp, challenge_id))
                return False

            if row["attempts"] >= row["max_attempts"]:
                return False
            if not row["consent_granted"]:
                return False

            import hmac
            if not hmac.compare_digest(row["proof_digest"], proof_digest):
                db.execute("""
                    UPDATE owner_endpoint_verification_challenges
                    SET attempts = attempts + 1,
                        consumed_at = CASE
                            WHEN attempts + 1 >= max_attempts THEN ?
                            ELSE consumed_at
                        END
                    WHERE challenge_id = ? AND consumed_at IS NULL
                """, (timestamp, challenge_id))
                return False

            # Endpoint registration and challenge consumption share one
            # transaction: there is no verified-but-unregistered gap.
            db.execute("""
                INSERT INTO owner_communication_channels(
                    endpoint_id, business_id, user_id, channel,
                    encrypted_endpoint, key_version, endpoint_fingerprint,
                    verified_at, consent_granted_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                endpoint_id,
                row["business_id"],
                row["user_id"],
                row["channel"],
                row["encrypted_endpoint"],
                row["key_version"],
                row["endpoint_fingerprint"],
                timestamp,
                timestamp,
                timestamp,
                timestamp,
            ))

            updated = db.execute("""
                UPDATE owner_endpoint_verification_challenges
                SET consumed_at = ?
                WHERE challenge_id = ? AND consumed_at IS NULL
                  AND attempts < max_attempts
            """, (timestamp, challenge_id))

            if updated.rowcount != 1:
                raise RuntimeError("Endpoint challenge consumption failed.")

            return True


    def find_pending_endpoint_challenge(
        self, *, channel: str, fingerprint: str,
        provider_account_id: str, now: str | None = None,
    ) -> str | None:
        channel = _required(channel, "channel")
        provider_account_id = _required(
            provider_account_id, "provider_account_id"
        )
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint or ""):
            raise ValueError("A valid endpoint fingerprint is required.")

        timestamp = now or _now()
        with self.database.connection() as db:
            row = db.execute("""
                SELECT challenge_id
                FROM owner_endpoint_verification_challenges
                WHERE channel = ?
                  AND endpoint_fingerprint = ?
                  AND provider_account_id = ?
                  AND consent_granted = 1
                  AND consumed_at IS NULL
                  AND expires_at > ?
                  AND attempts < max_attempts
                ORDER BY created_at DESC
                LIMIT 1
            """, (
                channel, fingerprint, provider_account_id, timestamp,
            )).fetchone()
        return row["challenge_id"] if row is not None else None

    def claim_endpoint_verification_message(
        self, *, provider_account_id: str,
        provider_message_id: str,
    ) -> bool:
        provider_account_id = _required(
            provider_account_id, "provider_account_id"
        )
        provider_message_id = _required(
            provider_message_id, "provider_message_id"
        )
        with self.database.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS
                owner_endpoint_verification_inbound_messages (
                    provider_account_id TEXT NOT NULL,
                    provider_message_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (provider_account_id, provider_message_id)
                )
            """)
            result = db.execute("""
                INSERT OR IGNORE INTO
                owner_endpoint_verification_inbound_messages (
                    provider_account_id, provider_message_id, created_at
                ) VALUES (?, ?, ?)
            """, (
                provider_account_id, provider_message_id, _now(),
            ))
            return result.rowcount == 1

    def cancel_endpoint_challenge(
        self, *, challenge_id: str,
    ) -> bool:
        challenge_id = _required(challenge_id, "challenge_id")
        with self.database.transaction() as db:
            result = db.execute("""
                UPDATE owner_endpoint_verification_challenges
                SET consumed_at = ?
                WHERE challenge_id = ?
                  AND consumed_at IS NULL
            """, (_now(), challenge_id))
            return result.rowcount == 1

