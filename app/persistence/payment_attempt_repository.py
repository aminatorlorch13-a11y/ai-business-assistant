from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage


class SQLitePaymentAttemptRepository:
    """Persist provider checkout attempts without granting paid access.

    Settlement must happen through the verified-purchase boundary, never
    through this repository's ordinary status-update methods.
    """

    _OPEN_STATUSES = ("created", "checkout_created", "pending")
    _TRANSITIONS = {
        "created": {"checkout_created", "pending", "failed", "expired", "cancelled"},
        "checkout_created": {"pending", "failed", "expired", "cancelled"},
        "pending": {"failed", "expired", "cancelled"},
        "failed": set(),
        "expired": set(),
        "cancelled": set(),
    }

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def create_attempt(
        self,
        *,
        attempt_id: str,
        business_id: str,
        subscription_id: str,
        provider: str,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        now: datetime,
        expires_at: datetime | None = None,
    ) -> dict:
        _required(attempt_id, "attempt_id", 128)
        _required(business_id, "business_id", 128)
        _required(subscription_id, "subscription_id", 128)
        _required(provider, "provider", 128)
        _required(idempotency_key, "idempotency_key", 256)
        _money(amount)
        _currency(currency)
        timestamp = datetime_to_storage(now)
        expiry = datetime_to_storage(expires_at) if expires_at is not None else None

        with self._database.transaction() as connection:
            subscription = connection.execute(
                """SELECT business_id, status
                   FROM business_subscriptions
                   WHERE subscription_id = ?""",
                (subscription_id,),
            ).fetchone()

            if subscription is None or subscription["business_id"] != business_id:
                raise ValueError("Subscription does not belong to this business.")

            existing = connection.execute(
                """SELECT * FROM payment_attempts
                   WHERE business_id = ? AND idempotency_key = ?""",
                (business_id, idempotency_key),
            ).fetchone()

            if existing is not None:
                expected = (
                    subscription_id, provider, str(amount), currency
                )
                actual = (
                    existing["subscription_id"],
                    existing["provider"],
                    existing["amount"],
                    existing["currency"],
                )
                if actual != expected:
                    raise ValueError(
                        "Idempotency key was already used for a different payment."
                    )
                return dict(existing)

            try:
                connection.execute(
                    """INSERT INTO payment_attempts
                       (attempt_id, business_id, subscription_id, provider,
                        idempotency_key, amount, currency, status,
                        created_at, updated_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?)""",
                    (
                        attempt_id, business_id, subscription_id, provider,
                        idempotency_key, str(amount), currency,
                        timestamp, timestamp, expiry,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Payment attempt could not be created.") from exc

            row = connection.execute(
                "SELECT * FROM payment_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            return dict(row)

    def get_attempt(self, attempt_id: str) -> dict | None:
        _required(attempt_id, "attempt_id", 128)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM payment_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_by_idempotency_key(
        self, *, business_id: str, idempotency_key: str
    ) -> dict | None:
        _required(business_id, "business_id", 128)
        _required(idempotency_key, "idempotency_key", 256)
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM payment_attempts
                   WHERE business_id = ? AND idempotency_key = ?""",
                (business_id, idempotency_key),
            ).fetchone()
        return dict(row) if row is not None else None

    def find_open_attempt(
        self, *, business_id: str, subscription_id: str
    ) -> dict | None:
        _required(business_id, "business_id", 128)
        _required(subscription_id, "subscription_id", 128)
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM payment_attempts
                   WHERE business_id = ? AND subscription_id = ?
                     AND status IN ('created', 'checkout_created', 'pending')
                   ORDER BY created_at DESC LIMIT 1""",
                (business_id, subscription_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def record_checkout(
        self,
        *,
        attempt_id: str,
        business_id: str,
        checkout_url: str,
        provider_checkout_id: str | None,
        now: datetime,
    ) -> dict:
        _required(attempt_id, "attempt_id", 128)
        _required(business_id, "business_id", 128)
        _validate_checkout_url(checkout_url)
        if provider_checkout_id is not None:
            _required(provider_checkout_id, "provider_checkout_id", 256)
        timestamp = datetime_to_storage(now)

        with self._database.transaction() as connection:
            row = connection.execute(
                """SELECT * FROM payment_attempts
                   WHERE attempt_id = ? AND business_id = ?""",
                (attempt_id, business_id),
            ).fetchone()
            if row is None:
                raise ValueError("Payment attempt does not belong to this business.")

            if row["status"] == "checkout_created":
                if (
                    row["checkout_url"] == checkout_url
                    and row["provider_checkout_id"] == provider_checkout_id
                ):
                    return dict(row)
                raise ValueError("Checkout details cannot be replaced.")

            if row["status"] != "created":
                raise ValueError("Checkout cannot be recorded in the current state.")

            try:
                connection.execute(
                    """UPDATE payment_attempts
                       SET checkout_url = ?, provider_checkout_id = ?,
                           status = 'checkout_created', updated_at = ?
                       WHERE attempt_id = ? AND business_id = ?
                         AND status = 'created'""",
                    (
                        checkout_url, provider_checkout_id, timestamp,
                        attempt_id, business_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Provider checkout identifier is already in use."
                ) from exc

            updated = connection.execute(
                "SELECT * FROM payment_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            return dict(updated)

    def update_status(
        self,
        *,
        attempt_id: str,
        business_id: str,
        status: str,
        now: datetime,
        failure_reason: str | None = None,
    ) -> dict:
        """Apply a permitted non-settlement status transition.

        This method deliberately rejects 'settled'. Verified settlement
        belongs to the existing verified-purchase application boundary.
        """
        _required(attempt_id, "attempt_id", 128)
        _required(business_id, "business_id", 128)
        if status == "settled":
            raise ValueError(
                "Settlement requires the verified-purchase boundary."
            )
        if status not in self._TRANSITIONS:
            raise ValueError("Unsupported payment attempt status.")
        if failure_reason is not None:
            _required(failure_reason, "failure_reason", 1000)
        timestamp = datetime_to_storage(now)

        with self._database.transaction() as connection:
            row = connection.execute(
                """SELECT * FROM payment_attempts
                   WHERE attempt_id = ? AND business_id = ?""",
                (attempt_id, business_id),
            ).fetchone()
            if row is None:
                raise ValueError("Payment attempt does not belong to this business.")

            current = row["status"]
            if status == current:
                if failure_reason == row["failure_reason"]:
                    return dict(row)
                raise ValueError("An existing payment status cannot be rewritten.")

            if status not in self._TRANSITIONS.get(current, set()):
                raise ValueError(
                    f"Invalid payment attempt transition: {current} to {status}."
                )

            connection.execute(
                """UPDATE payment_attempts
                   SET status = ?, failure_reason = ?, updated_at = ?
                   WHERE attempt_id = ? AND business_id = ? AND status = ?""",
                (
                    status, failure_reason, timestamp,
                    attempt_id, business_id, current,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM payment_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            return dict(updated)


def _required(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters.")


def _money(value: object) -> None:
    if not isinstance(value, Decimal):
        raise TypeError("amount must be a Decimal.")
    if not value.is_finite() or value <= 0:
        raise ValueError("amount must be finite and greater than zero.")


def _currency(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value.upper() != value
    ):
        raise ValueError("currency must be a three-letter uppercase currency code.")


def _validate_checkout_url(value: str) -> None:
    _required(value, "checkout_url", 2048)
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            valid = False
    except ValueError:
        valid = False

    if not valid:
        raise ValueError("checkout_url must be a valid HTTPS URL without credentials or a fragment.")
