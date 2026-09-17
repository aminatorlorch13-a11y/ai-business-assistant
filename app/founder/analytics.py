from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.commercial.state import CommercialStatus
from app.platform.events import PlatformEventOutcome
from app.persistence.database import SQLiteDatabase


@dataclass(frozen=True)
class FounderMetric:
    value: int | str | None
    status: str
    source: str


@dataclass(frozen=True)
class FounderAnalytics:
    businesses: FounderMetric
    active_businesses: FounderMetric
    trial_businesses: FounderMetric
    expired_businesses: FounderMetric
    suspended_businesses: FounderMetric
    trials_started: FounderMetric
    trial_conversions: FounderMetric
    trial_conversion_rate: FounderMetric
    revenue: FounderMetric
    verified_purchases: FounderMetric
    recorded_events: FounderMetric
    successful_events: FounderMetric
    failed_events: FounderMetric
    denied_events: FounderMetric
    error_events: FounderMetric
    execution_volume: FounderMetric
    integration_health: FounderMetric
    website_visitors: FounderMetric
    website_page_views: FounderMetric
    channel_events: dict[str, int]


class FounderAnalyticsService:
    """Read-only Founder analytics over authoritative persisted evidence.

    This service never manufactures telemetry. Metrics whose underlying
    instrumentation does not yet exist are explicitly marked unavailable.
    """

    _NOT_INSTRUMENTED = "not_instrumented"
    _DATABASE = "database"

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def summary(self) -> FounderAnalytics:
        with self._database.connection() as connection:
            businesses = self._count(
                connection,
                "SELECT COUNT(*) FROM businesses",
            )

            states = self._state_counts(connection)

            trials_started = self._count(
                connection,
                "SELECT COUNT(*) FROM business_trials",
            )

            trial_conversions = self._count(
                connection,
                """
                SELECT COUNT(DISTINCT t.business_id)
                FROM business_trials AS t
                INNER JOIN purchase_records AS p
                    ON p.business_id = t.business_id
                   AND p.paid_at >= t.started_at
                """,
            )

            verified_purchases, revenue = self._purchase_totals(connection)
            event_counts = self._event_counts(connection)
            channel_events = self._channel_counts(connection)

        conversion_rate = (
            f"{(Decimal(trial_conversions) / Decimal(trials_started) * Decimal('100')):.2f}%"
            if trials_started
            else "0.00%"
        )

        return FounderAnalytics(
            businesses=self._available(businesses),
            active_businesses=self._available(states["active"]),
            trial_businesses=self._available(states["trial"]),
            expired_businesses=self._available(states["expired"]),
            suspended_businesses=self._available(states["suspended"]),
            trials_started=self._available(trials_started),
            trial_conversions=self._available(trial_conversions),
            trial_conversion_rate=self._available(conversion_rate),
            revenue=self._available(revenue),
            verified_purchases=self._available(verified_purchases),
            recorded_events=self._available(event_counts["total"]),
            successful_events=self._available(event_counts["success"]),
            failed_events=self._available(event_counts["failure"]),
            denied_events=self._available(event_counts["denied"]),
            error_events=self._available(event_counts["error"]),
            execution_volume=self._not_instrumented_metric(
                "assistant execution telemetry is not yet instrumented",
            ),
            integration_health=self._not_instrumented_metric(
                "integration health telemetry is not yet instrumented",
            ),
            website_visitors=self._not_instrumented_metric(
                "public website telemetry does not yet exist",
            ),
            website_page_views=self._not_instrumented_metric(
                "public website telemetry does not yet exist",
            ),
            channel_events=channel_events,
        )

    @staticmethod
    def _count(connection: Any, query: str) -> int:
        row = connection.execute(query).fetchone()
        return int(row[0])

    @staticmethod
    def _state_counts(connection: Any) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM commercial_states
            GROUP BY status
            """
        ).fetchall()

        counts = {status.value: 0 for status in CommercialStatus}

        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["count"])

        return counts

    @staticmethod
    def _purchase_totals(connection: Any) -> tuple[int, str]:
        rows = connection.execute(
            """
            SELECT amount, currency
            FROM purchase_records
            ORDER BY recorded_at ASC
            """
        ).fetchall()

        totals: dict[str, Decimal] = {}

        for row in rows:
            currency = str(row["currency"]).upper()
            try:
                amount = Decimal(str(row["amount"]))
            except Exception as exc:
                raise RuntimeError(
                    "Invalid persisted purchase amount."
                ) from exc

            totals[currency] = totals.get(currency, Decimal("0")) + amount

        purchase_count = len(rows)

        if not totals:
            return purchase_count, "0.00"

        if len(totals) == 1:
            currency, amount = next(iter(totals.items()))
            return purchase_count, f"{currency} {amount:.2f}"

        formatted = ", ".join(
            f"{currency} {amount:.2f}"
            for currency, amount in sorted(totals.items())
        )
        return purchase_count, formatted

    @staticmethod
    def _event_counts(connection: Any) -> dict[str, int]:
        counts = {
            outcome.value: 0
            for outcome in PlatformEventOutcome
            if outcome is not PlatformEventOutcome.UNKNOWN
        }
        counts["total"] = 0

        rows = connection.execute(
            """
            SELECT outcome, COUNT(*) AS count
            FROM platform_events
            GROUP BY outcome
            """
        ).fetchall()

        for row in rows:
            outcome = str(row["outcome"])
            count = int(row["count"])
            counts["total"] += count
            if outcome in counts:
                counts[outcome] = count

        return counts

    @staticmethod
    def _channel_counts(connection: Any) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT channel, COUNT(*) AS count
            FROM platform_events
            GROUP BY channel
            ORDER BY channel ASC
            """
        ).fetchall()

        return {
            str(row["channel"]): int(row["count"])
            for row in rows
        }

    @classmethod
    def _available(cls, value: int | str) -> FounderMetric:
        return FounderMetric(
            value=value,
            status="available",
            source=cls._DATABASE,
        )

    @classmethod
    def _not_instrumented_metric(cls, reason: str) -> FounderMetric:
        return FounderMetric(
            value=None,
            status=cls._NOT_INSTRUMENTED,
            source=reason,
        )
