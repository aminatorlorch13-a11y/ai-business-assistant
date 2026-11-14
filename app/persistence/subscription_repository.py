from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage


class SQLiteSubscriptionRepository:
    """Persist subscription administration without granting execution access."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def create_plan(
        self, *, plan_id: str, name: str, amount: Decimal,
        currency: str, interval_months: int, now: datetime,
    ) -> None:
        _required(plan_id, "plan_id", 128)
        _required(name, "name", 160)
        _money(amount)
        _currency(currency)
        _positive_int(interval_months, "interval_months")
        timestamp = datetime_to_storage(now)

        with self._database.transaction() as connection:
            try:
                connection.execute(
                    """INSERT INTO subscription_plans
                    (plan_id, name, amount, currency, interval_months,
                     active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (plan_id, name, str(amount), currency, interval_months,
                     timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Subscription plan could not be created.") from exc

    def create_subscription(
        self, *, subscription_id: str, business_id: str,
        plan_id: str, now: datetime,
    ) -> None:
        _required(subscription_id, "subscription_id", 128)
        _required(business_id, "business_id", 128)
        _required(plan_id, "plan_id", 128)
        timestamp = datetime_to_storage(now)

        with self._database.transaction() as connection:
            plan = connection.execute(
                "SELECT active FROM subscription_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if plan is None or plan["active"] != 1:
                raise ValueError("An active subscription plan is required.")

            try:
                connection.execute(
                    """INSERT INTO business_subscriptions
                    (subscription_id, business_id, plan_id, status,
                     created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', ?, ?)""",
                    (subscription_id, business_id, plan_id, timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Subscription could not be created; check business and existing subscription."
                ) from exc

    def get_subscription(self, subscription_id: str) -> dict | None:
        _required(subscription_id, "subscription_id", 128)
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT subscription_id, business_id, plan_id, status,
                          current_period_start, current_period_end,
                          cancel_at_period_end, cancelled_at,
                          created_at, updated_at
                   FROM business_subscriptions
                   WHERE subscription_id = ?""",
                (subscription_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def cancel_subscription(
        self, *, subscription_id: str, cancelled_at: datetime,
        at_period_end: bool = True,
    ) -> bool:
        """Cancel renewal or cancel immediately without changing business access."""
        _required(subscription_id, "subscription_id", 128)
        if not isinstance(cancelled_at, datetime):
            raise TypeError("cancelled_at must be a datetime.")
        if not isinstance(at_period_end, bool):
            raise TypeError("at_period_end must be a bool.")

        timestamp = datetime_to_storage(cancelled_at)
        with self._database.transaction() as connection:
            subscription = connection.execute(
                """SELECT status, current_period_end, cancel_at_period_end
                   FROM business_subscriptions WHERE subscription_id = ?""",
                (subscription_id,),
            ).fetchone()

            if subscription is None:
                raise ValueError("Subscription does not exist.")

            status = subscription["status"]
            if status in ("cancelled", "expired"):
                return False
            if status not in ("pending", "active", "past_due"):
                raise ValueError("Subscription cannot be cancelled from its current state.")

            if at_period_end:
                if status == "pending" or subscription["current_period_end"] is None:
                    raise ValueError(
                        "A subscription without a paid period must be cancelled immediately."
                    )
                if subscription["cancel_at_period_end"]:
                    return False

                connection.execute(
                    """UPDATE business_subscriptions
                       SET cancel_at_period_end = 1, updated_at = ?
                       WHERE subscription_id = ?""",
                    (timestamp, subscription_id),
                )
            else:
                connection.execute(
                    """UPDATE business_subscriptions
                       SET status = 'cancelled', cancel_at_period_end = 0,
                           cancelled_at = ?, updated_at = ?
                       WHERE subscription_id = ?""",
                    (timestamp, timestamp, subscription_id),
                )
                connection.execute(
                    """UPDATE manual_payment_requests
                       SET status = 'cancelled'
                       WHERE subscription_id = ? AND status = 'pending'""",
                    (subscription_id,),
                )

            # Local mandate revocation only; no provider-side action is claimed.
            connection.execute(
                """UPDATE recurring_payment_mandates
                   SET status = 'revoked', revoked_at = ?, updated_at = ?
                   WHERE subscription_id = ? AND status IN ('pending', 'active')""",
                (timestamp, timestamp, subscription_id),
            )

        return True

    def create_recurring_mandate(
        self, *, mandate_id: str, subscription_id: str,
        provider: str, provider_mandate_id: str,
        approved_by_user_id: str, approved_at: datetime,
        consent_version: str, now: datetime,
    ) -> None:
        for value, field in (
            (mandate_id, "mandate_id"),
            (subscription_id, "subscription_id"),
            (provider, "provider"),
            (provider_mandate_id, "provider_mandate_id"),
            (approved_by_user_id, "approved_by_user_id"),
            (consent_version, "consent_version"),
        ):
            _required(value, field, 256)

        approved = datetime_to_storage(approved_at)
        created = datetime_to_storage(now)

        with self._database.transaction() as connection:
            try:
                connection.execute(
                    """INSERT INTO recurring_payment_mandates
                    (mandate_id, subscription_id, provider,
                     provider_mandate_id, status, approved_by_user_id,
                     approved_at, consent_version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
                    (mandate_id, subscription_id, provider,
                     provider_mandate_id, approved_by_user_id,
                     approved, consent_version, created, created),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Recurring mandate could not be recorded.") from exc

    def revoke_recurring_mandate(
        self, *, mandate_id: str, revoked_at: datetime,
    ) -> bool:
        _required(mandate_id, "mandate_id", 128)
        timestamp = datetime_to_storage(revoked_at)

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE recurring_payment_mandates
                   SET status = 'revoked', revoked_at = ?, updated_at = ?
                   WHERE mandate_id = ? AND status IN ('pending', 'active')""",
                (timestamp, timestamp, mandate_id),
            )
        return cursor.rowcount == 1

    def submit_manual_payment(
        self, *, request_id: str, business_id: str,
        subscription_id: str, submitted_by_user_id: str,
        amount: Decimal, currency: str, payment_reference: str,
        evidence_reference: str | None, submitted_at: datetime,
    ) -> None:
        for value, field in (
            (request_id, "request_id"),
            (business_id, "business_id"),
            (subscription_id, "subscription_id"),
            (submitted_by_user_id, "submitted_by_user_id"),
            (payment_reference, "payment_reference"),
        ):
            _required(value, field, 256)

        _money(amount)
        _currency(currency)
        if evidence_reference is not None:
            _required(evidence_reference, "evidence_reference", 1024)

        timestamp = datetime_to_storage(submitted_at)

        with self._database.transaction() as connection:
            subscription = connection.execute(
                """SELECT business_id, status
                   FROM business_subscriptions WHERE subscription_id = ?""",
                (subscription_id,),
            ).fetchone()

            if subscription is None or subscription["business_id"] != business_id:
                raise ValueError("Subscription does not belong to this business.")
            if subscription["status"] in ("cancelled", "expired"):
                raise ValueError("This subscription cannot accept a payment request.")

            try:
                connection.execute(
                    """INSERT INTO manual_payment_requests
                    (request_id, business_id, subscription_id,
                     submitted_by_user_id, amount, currency,
                     payment_reference, evidence_reference,
                     status, submitted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                    (request_id, business_id, subscription_id,
                     submitted_by_user_id, str(amount), currency,
                     payment_reference, evidence_reference, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Manual payment request could not be submitted.") from exc

    def list_pending_manual_payments(self, *, limit: int = 100) -> list[dict]:
        _positive_int(limit, "limit")
        if limit > 500:
            raise ValueError("limit must not exceed 500.")

        with self._database.connection() as connection:
            rows = connection.execute(
                """SELECT request_id, business_id, subscription_id,
                          amount, currency, payment_reference,
                          evidence_reference, submitted_at
                   FROM manual_payment_requests
                   WHERE status = 'pending'
                   ORDER BY submitted_at ASC, request_id ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def review_manual_payment(
        self, *, request_id: str, reviewer_user_id: str,
        decision: str, reason: str, reviewed_at: datetime,
    ) -> bool:
        _required(request_id, "request_id", 128)
        _required(reviewer_user_id, "reviewer_user_id", 128)
        _required(reason, "reason", 1000)

        if decision not in ("verified", "rejected"):
            raise ValueError("decision must be 'verified' or 'rejected'.")

        timestamp = datetime_to_storage(reviewed_at)

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE manual_payment_requests
                   SET status = ?, reviewed_by_user_id = ?,
                       review_reason = ?, reviewed_at = ?
                   WHERE request_id = ? AND status = 'pending'""",
                (decision, reviewer_user_id, reason, timestamp, request_id),
            )
        return cursor.rowcount == 1


def _required(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string.")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty.")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters.")


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
        or value != value.upper()
    ):
        raise ValueError("currency must be three uppercase ASCII letters.")


def _positive_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer.")
    if value <= 0:
        raise ValueError(f"{field} must be greater than zero.")
