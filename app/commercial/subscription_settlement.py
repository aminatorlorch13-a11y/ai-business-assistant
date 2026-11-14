from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage


@dataclass(frozen=True)
class SubscriptionSettlementResult:
    subscription_id: str
    business_id: str
    provider: str
    provider_event_id: str
    processed: bool
    duplicate: bool
    period_start: datetime | None = None
    period_end: datetime | None = None

    def __post_init__(self) -> None:
        if self.processed == self.duplicate:
            raise ValueError("Settlement outcomes must be distinct.")


class SQLiteSubscriptionSettlementService:
    """Atomically settle a subscription using a verified payment fact."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def settle(
        self,
        *,
        subscription_id: str,
        purchase: VerifiedPurchase,
        recorded_at: datetime,
        mandate_id: str | None = None,
    ) -> SubscriptionSettlementResult:
        if not isinstance(purchase, VerifiedPurchase):
            raise TypeError("purchase must be a VerifiedPurchase.")
        if not isinstance(subscription_id, str) or not subscription_id.strip():
            raise ValueError("subscription_id must be non-empty.")
        if len(subscription_id) > 128:
            raise ValueError("subscription_id exceeds 128 characters.")
        if mandate_id is not None:
            if not isinstance(mandate_id, str) or not mandate_id.strip():
                raise ValueError("mandate_id must be non-empty when supplied.")
            if len(mandate_id) > 128:
                raise ValueError("mandate_id exceeds 128 characters.")

        record = PurchaseRecord(purchase=purchase, recorded_at=recorded_at)
        recorded_timestamp = datetime_to_storage(record.recorded_at)
        paid_timestamp = datetime_to_storage(purchase.paid_at)

        with self._database.transaction() as connection:
            subscription = connection.execute(
                """
                SELECT s.subscription_id, s.business_id, s.plan_id, s.status,
                       s.current_period_start, s.current_period_end,
                       s.cancel_at_period_end,
                       p.amount, p.currency, p.interval_months, p.active
                FROM business_subscriptions AS s
                JOIN subscription_plans AS p ON p.plan_id = s.plan_id
                WHERE s.subscription_id = ?
                """,
                (subscription_id,),
            ).fetchone()

            if subscription is None:
                raise ValueError("Subscription does not exist.")
            if subscription["business_id"] != purchase.business_id:
                raise ValueError("Verified purchase belongs to another business.")
            if subscription["active"] != 1:
                raise ValueError("The subscription plan is inactive.")
            if subscription["status"] not in ("pending", "active", "past_due"):
                raise ValueError("This subscription cannot be settled.")
            if subscription["cancel_at_period_end"] == 1:
                raise ValueError("A subscription scheduled for cancellation cannot renew.")

            if Decimal(subscription["amount"]) != purchase.amount:
                raise ValueError("Verified payment amount does not match the subscription plan.")
            if subscription["currency"] != purchase.currency:
                raise ValueError("Verified payment currency does not match the subscription plan.")

            if mandate_id is not None:
                mandate = connection.execute(
                    """
                    SELECT subscription_id, status, provider
                    FROM recurring_payment_mandates
                    WHERE mandate_id = ?
                    """,
                    (mandate_id,),
                ).fetchone()
                if (
                    mandate is None
                    or mandate["subscription_id"] != subscription_id
                    or mandate["status"] != "active"
                    or mandate["provider"] != purchase.provider
                ):
                    raise ValueError("An active mandate for this subscription is required.")

            try:
                connection.execute(
                    """
                    INSERT INTO purchase_records(
                        provider, provider_event_id, business_id,
                        amount, currency, paid_at, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.provider,
                        record.provider_event_id,
                        record.business_id,
                        str(purchase.amount),
                        purchase.currency,
                        paid_timestamp,
                        recorded_timestamp,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    """
                    SELECT 1 FROM purchase_records
                    WHERE provider = ? AND provider_event_id = ?
                    """,
                    (purchase.provider, purchase.provider_event_id),
                ).fetchone()
                if existing is not None:
                    return SubscriptionSettlementResult(
                        subscription_id=subscription_id,
                        business_id=purchase.business_id,
                        provider=purchase.provider,
                        provider_event_id=purchase.provider_event_id,
                        processed=False,
                        duplicate=True,
                    )
                raise ValueError("Verified purchase could not be recorded.")

            previous_period = None
            first_period = None
            if subscription["current_period_end"] is not None:
                previous_period = connection.execute(
                    """
                    SELECT period_end
                    FROM subscription_billing_periods
                    WHERE subscription_id = ?
                    ORDER BY period_end DESC
                    LIMIT 1
                    """,
                    (subscription_id,),
                ).fetchone()
                first_period = connection.execute(
                    """
                    SELECT period_start
                    FROM subscription_billing_periods
                    WHERE subscription_id = ?
                    ORDER BY period_start ASC
                    LIMIT 1
                    """,
                    (subscription_id,),
                ).fetchone()

            if previous_period is None or first_period is None:
                period_start = purchase.paid_at
                anchor_day = period_start.day
            else:
                previous_end = datetime.fromisoformat(previous_period["period_end"])
                original_start = datetime.fromisoformat(first_period["period_start"])
                period_start = max(purchase.paid_at, previous_end)
                anchor_day = original_start.day

            period_end = _add_calendar_months(
                period_start,
                subscription["interval_months"],
                anchor_day,
            )

            connection.execute(
                """
                INSERT INTO subscription_billing_periods(
                    billing_period_id, subscription_id, business_id,
                    provider, provider_event_id, period_start, period_end,
                    amount, currency, paid_at, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    subscription_id,
                    purchase.business_id,
                    purchase.provider,
                    purchase.provider_event_id,
                    datetime_to_storage(period_start),
                    datetime_to_storage(period_end),
                    str(purchase.amount),
                    purchase.currency,
                    paid_timestamp,
                    recorded_timestamp,
                ),
            )

            connection.execute(
                """
                UPDATE business_subscriptions
                SET status = 'active',
                    current_period_start = ?,
                    current_period_end = ?,
                    updated_at = ?
                WHERE subscription_id = ?
                """,
                (
                    datetime_to_storage(period_start),
                    datetime_to_storage(period_end),
                    recorded_timestamp,
                    subscription_id,
                ),
            )

            connection.execute(
                """
                INSERT INTO commercial_states(business_id, status)
                VALUES (?, 'active')
                ON CONFLICT(business_id)
                DO UPDATE SET status = 'active'
                """,
                (purchase.business_id,),
            )

            inserted = connection.execute(
                "INSERT OR IGNORE INTO paid_business_ledger(business_id) VALUES (?)",
                (purchase.business_id,),
            ).rowcount

            if inserted == 1:
                connection.execute(
                    """
                    UPDATE launch_program
                    SET paid_businesses =
                        MIN(target_businesses, paid_businesses + 1)
                    WHERE singleton_id = 1
                    """
                )

        return SubscriptionSettlementResult(
            subscription_id=subscription_id,
            business_id=purchase.business_id,
            provider=purchase.provider,
            provider_event_id=purchase.provider_event_id,
            processed=True,
            duplicate=False,
            period_start=period_start,
            period_end=period_end,
        )


def _add_calendar_months(
    value: datetime,
    months: int,
    anchor_day: int,
) -> datetime:
    if isinstance(months, bool) or not isinstance(months, int) or months <= 0:
        raise ValueError("months must be a positive integer.")
    if isinstance(anchor_day, bool) or not isinstance(anchor_day, int):
        raise TypeError("anchor_day must be an integer.")

    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])

    return value.replace(year=year, month=month, day=day)
