from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
import uuid


SEVERITIES = {"critical", "important", "routine"}
ACTIONS = {"interrupt", "deliver", "defer", "briefing", "queue"}
STATUSES = {"queued", "deferred", "briefing", "delivered", "acknowledged", "failed"}
PENDING_STATUSES = {"queued", "deferred", "briefing"}


@dataclass(frozen=True, slots=True)
class AttentionEvent:
    event_id: str
    business_id: str
    user_id: str
    idempotency_key: str
    event_type: str
    severity: str
    title: str
    details: str
    payload: dict
    action: str
    reason: str
    evaluated_at: str
    local_time: str
    quiet_hours_active: bool
    deliver_after: str | None
    status: str
    attempts: int
    provider_message_id: str | None
    last_attempt_at: str | None
    delivered_at: str | None
    acknowledged_at: str | None
    failure_reason: str | None
    created_at: str
    updated_at: str
    claim_token: str | None = None
    claimed_by: str | None = None
    claimed_at: str | None = None
    lease_expires_at: str | None = None
    retry_after: str | None = None


class SQLiteAttentionEventRepository:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def from_row(row):
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        data["quiet_hours_active"] = bool(data["quiet_hours_active"])
        return AttentionEvent(**data)

    def get(self, business_id, user_id, event_id):
        with self.database.connection() as conn:
            row = conn.execute("""
                SELECT * FROM attention_events
                WHERE business_id=? AND user_id=? AND event_id=?
            """, (business_id, user_id, event_id)).fetchone()
        return self.from_row(row) if row else None

    def create(
        self, business_id, user_id, *, idempotency_key, event_type,
        severity, title, decision, details="", payload=None,
    ):
        if not all(isinstance(v, str) and v.strip() for v in (
            business_id, user_id, idempotency_key, event_type, title
        )):
            raise ValueError("Business, user, idempotency key, event type and title are required.")
        if severity not in SEVERITIES:
            raise ValueError("Invalid event severity.")
        if decision.action not in ACTIONS:
            raise ValueError("Invalid attention decision.")
        if not isinstance(details, str):
            raise ValueError("Event details must be text.")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("Event payload must be an object.")

        try:
            payload_json = json.dumps(payload, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Event payload must contain valid JSON data.") from exc

        now = self.now()
        event_id = str(uuid.uuid4())
        status = {
            "interrupt": "queued",
            "deliver": "queued",
            "defer": "deferred",
            "briefing": "briefing",
            "queue": "queued",
        }[decision.action]

        with self.database.connection() as conn:
            conn.execute("""
                INSERT INTO attention_events (
                    event_id,business_id,user_id,idempotency_key,event_type,
                    severity,title,details,payload_json,action,reason,
                    evaluated_at,local_time,quiet_hours_active,deliver_after,
                    status,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(business_id,user_id,idempotency_key) DO NOTHING
            """, (
                event_id,business_id,user_id,idempotency_key,event_type,
                severity,title,details,payload_json,decision.action,decision.reason,
                decision.evaluated_at,decision.local_time,
                int(decision.quiet_hours_active),decision.deliver_after,
                status,now,now,
            ))
            row = conn.execute("""
                SELECT * FROM attention_events
                WHERE business_id=? AND user_id=? AND idempotency_key=?
            """, (business_id,user_id,idempotency_key)).fetchone()
        return self.from_row(row)

    def list_events(self, business_id, user_id, status=None, limit=50):
        if status is not None and status not in STATUSES:
            raise ValueError("Invalid event status.")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100.")

        query = """
            SELECT * FROM attention_events
            WHERE business_id=? AND user_id=?
        """
        params = [business_id, user_id]
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.database.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self.from_row(row) for row in rows]

    def claim_due_events(
        self,
        business_id,
        user_id,
        worker_id,
        *,
        limit=10,
        lease_seconds=60,
        now=None,
        actions=None,
    ):
        """Atomically claim due events for one worker.

        A live lease cannot be stolen. Expired leases are reclaimable.
        Claiming does not increment the delivery-attempt counter.
        """
        if not all(
            isinstance(value, str) and value.strip()
            for value in (business_id, user_id, worker_id)
        ):
            raise ValueError("Business, user and worker identifiers are required.")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100.")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Lease duration must be between 1 and 3600 seconds.")

        if actions is not None:
            actions = tuple(actions)
            if not actions or any(action not in ACTIONS for action in actions):
                raise ValueError("Invalid event actions.")

        action_filter = ""
        if actions is not None:
            action_filter = " AND action IN (" + ",".join("?" for _ in actions) + ")"

        now_dt = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        now_value = now_dt.astimezone(timezone.utc).isoformat()
        expiry = (
            now_dt.astimezone(timezone.utc)
            + __import__("datetime").timedelta(seconds=lease_seconds)
        ).isoformat()

        claimed = []
        with self.database.transaction() as conn:
            candidates = conn.execute(f"""
                SELECT event_id
                FROM attention_events
                WHERE business_id=? AND user_id=?
                  AND status IN ('queued', 'deferred', 'briefing')
                  AND (deliver_after IS NULL OR deliver_after <= ?)
                  AND (retry_after IS NULL OR retry_after <= ?)
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                {action_filter}
                ORDER BY
                  CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'important' THEN 1
                    ELSE 2
                  END,
                  created_at ASC
                LIMIT ?
            """, (
                business_id, user_id, now_value, now_value, now_value,
                *(actions or ()), limit
            )).fetchall()

            for candidate in candidates:
                token = str(uuid.uuid4())
                cursor = conn.execute(f"""
                    UPDATE attention_events
                    SET claim_token=?, claimed_by=?, claimed_at=?,
                        lease_expires_at=?, updated_at=?
                    WHERE business_id=? AND user_id=? AND event_id=?
                      AND status IN ('queued', 'deferred', 'briefing')
                      AND (deliver_after IS NULL OR deliver_after <= ?)
                      AND (retry_after IS NULL OR retry_after <= ?)
                      AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                      {action_filter}
                """, (
                    token, worker_id, now_value, expiry, now_value,
                    business_id, user_id, candidate["event_id"],
                    now_value, now_value, now_value,
                    *(actions or ()),
                ))
                if cursor.rowcount == 1:
                    row = conn.execute("""
                        SELECT * FROM attention_events
                        WHERE business_id=? AND user_id=? AND event_id=?
                          AND claim_token=?
                    """, (
                        business_id, user_id, candidate["event_id"], token
                    )).fetchone()
                    if row:
                        claimed.append(self.from_row(row))

        return claimed

    def release_claim(
        self,
        business_id,
        user_id,
        event_id,
        claim_token,
        *,
        reason,
        retry_after=None,
    ):
        """Release a worker's claim, optionally scheduling a later retry."""
        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("A claim token is required.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A release reason is required.")
        if retry_after is not None and (
            not isinstance(retry_after, str) or not retry_after.strip()
        ):
            raise ValueError("Retry time must be a non-empty ISO timestamp.")

        now = self.now()
        with self.database.transaction() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET claim_token=NULL, claimed_by=NULL, claimed_at=NULL,
                    lease_expires_at=NULL, retry_after=?, failure_reason=?,
                    updated_at=?
                WHERE business_id=? AND user_id=? AND event_id=?
                  AND claim_token=?
                  AND lease_expires_at > ?
                  AND status IN ('queued', 'deferred', 'briefing')
            """, (
                retry_after, reason.strip(), now,
                business_id, user_id, event_id, claim_token, now,
            ))
            if cursor.rowcount != 1:
                raise ValueError("Claim is missing, expired or no longer owned.")
        return self.get(business_id, user_id, event_id)

    def complete_claim(
        self, business_id, user_id, event_id, claim_token, provider_message_id,
        *, now=None,
    ):
        """Confirm delivery only when the caller still owns the event lease."""
        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("A claim token is required.")
        if not isinstance(provider_message_id, str) or not provider_message_id.strip():
            raise ValueError("A provider delivery reference is required.")

        now = now or self.now()
        with self.database.transaction() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET status='delivered', provider_message_id=?,
                    delivered_at=?, updated_at=?, failure_reason=NULL,
                    claim_token=NULL, claimed_by=NULL, claimed_at=NULL,
                    lease_expires_at=NULL, retry_after=NULL
                WHERE business_id=? AND user_id=? AND event_id=?
                  AND claim_token=?
                  AND lease_expires_at > ?
                  AND status IN ('queued', 'deferred', 'briefing')
            """, (
                provider_message_id, now, now,
                business_id, user_id, event_id, claim_token, now,
            ))
            if cursor.rowcount != 1:
                raise ValueError("Claim is missing, expired or no longer owned.")
        return self.get(business_id, user_id, event_id)

    def release_expired_claims(self, *, now=None, limit=100):
        """Clear expired leases so their events can be claimed again."""
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Limit must be between 1 and 500.")

        now_value = now or self.now()
        with self.database.transaction() as conn:
            rows = conn.execute("""
                SELECT event_id, business_id, user_id
                FROM attention_events
                WHERE lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                  AND status IN ('queued', 'deferred', 'briefing')
                ORDER BY lease_expires_at ASC
                LIMIT ?
            """, (now_value, limit)).fetchall()

            released = 0
            for row in rows:
                cursor = conn.execute("""
                    UPDATE attention_events
                    SET claim_token=NULL, claimed_by=NULL, claimed_at=NULL,
                        lease_expires_at=NULL, updated_at=?
                    WHERE business_id=? AND user_id=? AND event_id=?
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= ?
                      AND status IN ('queued', 'deferred', 'briefing')
                """, (
                    now_value, row["business_id"], row["user_id"],
                    row["event_id"], now_value,
                ))
                released += cursor.rowcount
        return released

    def record_claim_attempt(
        self, business_id, user_id, event_id, claim_token
    ):
        """Record a real delivery attempt under a currently valid lease."""
        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("A claim token is required.")

        now = self.now()
        with self.database.transaction() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET attempts=attempts+1, last_attempt_at=?, updated_at=?
                WHERE business_id=? AND user_id=? AND event_id=?
                  AND claim_token=? AND lease_expires_at > ?
                  AND status IN ('queued', 'deferred', 'briefing')
            """, (
                now, now, business_id, user_id, event_id, claim_token, now
            ))
            if cursor.rowcount != 1:
                raise ValueError("A valid, unexpired event claim is required.")
        return self.get(business_id, user_id, event_id)

    def record_attempt(self, business_id, user_id, event_id):
        now = self.now()
        with self.database.connection() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET attempts=attempts+1,last_attempt_at=?,updated_at=?
                WHERE business_id=? AND user_id=? AND event_id=?
                    AND status IN ('queued','deferred','briefing')
            """, (now,now,business_id,user_id,event_id))
            if cursor.rowcount != 1:
                raise ValueError("Event is missing or is no longer pending.")
        return self.get(business_id,user_id,event_id)

    def confirm_delivery(self, business_id, user_id, event_id, provider_message_id):
        if not isinstance(provider_message_id, str) or not provider_message_id.strip():
            raise ValueError("A provider delivery reference is required.")
        now = self.now()
        with self.database.connection() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET status='delivered',provider_message_id=?,
                    delivered_at=?,updated_at=?,failure_reason=NULL
                WHERE business_id=? AND user_id=? AND event_id=?
                    AND status IN ('queued','deferred','briefing')
            """, (
                provider_message_id,now,now,business_id,user_id,event_id
            ))
            if cursor.rowcount != 1:
                raise ValueError("Event is missing or is no longer pending.")
        return self.get(business_id,user_id,event_id)

    def acknowledge(self, business_id, user_id, event_id):
        now = self.now()
        with self.database.connection() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET status='acknowledged',acknowledged_at=?,updated_at=?
                WHERE business_id=? AND user_id=? AND event_id=?
                    AND status='delivered'
            """, (now,now,business_id,user_id,event_id))
            if cursor.rowcount != 1:
                raise ValueError("Only a delivered event can be acknowledged.")
        return self.get(business_id,user_id,event_id)

    def fail_claim(
        self, business_id, user_id, event_id, claim_token, reason
    ):
        """Atomically fail a claimed event and clear its worker lease."""
        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("A claim token is required.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A failure reason is required.")

        now = self.now()
        with self.database.transaction() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET status='failed',
                    failure_reason=?,
                    claim_token=NULL,
                    claimed_by=NULL,
                    claimed_at=NULL,
                    lease_expires_at=NULL,
                    updated_at=?
                WHERE business_id=? AND user_id=? AND event_id=?
                  AND claim_token=?
                  AND lease_expires_at > ?
                  AND status IN ('queued','deferred','briefing')
            """, (
                reason.strip(), now, business_id, user_id,
                event_id, claim_token, now,
            ))
            if cursor.rowcount != 1:
                raise ValueError("Claim is missing, expired or no longer pending.")

        return self.get(business_id, user_id, event_id)

    def mark_failed(self, business_id, user_id, event_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A failure reason is required.")
        now = self.now()
        with self.database.connection() as conn:
            cursor = conn.execute("""
                UPDATE attention_events
                SET status='failed',failure_reason=?,updated_at=?
                WHERE business_id=? AND user_id=? AND event_id=?
                    AND status IN ('queued','deferred','briefing')
            """, (reason.strip(),now,business_id,user_id,event_id))
            if cursor.rowcount != 1:
                raise ValueError("Event is missing or is no longer pending.")
        return self.get(business_id,user_id,event_id)
