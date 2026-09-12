from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage, datetime_to_storage


@dataclass(frozen=True)
class RateLimitPolicy:
    failure_threshold: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 300.0
    window_seconds: int = 900

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive.")
        if self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be positive.")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must not be smaller than base delay.")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive.")


@dataclass
class _AttemptState:
    failures: int
    first_failure_at: float
    blocked_until: float


class InMemoryAuthenticationRateLimiter:
    """Single-process strategy useful for tests/dev; not a production shared adapter."""

    def __init__(self, policy: RateLimitPolicy = RateLimitPolicy(), clock=time.monotonic) -> None:
        self._policy = policy
        self._clock = clock
        self._lock = Lock()
        self._states: dict[str, _AttemptState] = {}

    def allow(self, account_key: str, source_key: str) -> bool:
        now = self._clock()
        with self._lock:
            return all(
                (state := self._states.get(key)) is None or state.blocked_until <= now
                for key in _keys(account_key, source_key)
            )

    def record_failure(self, account_key: str, source_key: str) -> None:
        now = self._clock()
        with self._lock:
            for key in _keys(account_key, source_key):
                state = self._states.get(key)
                if state is None or now - state.first_failure_at > self._policy.window_seconds:
                    state = _AttemptState(0, now, 0.0)
                state.failures += 1
                if state.failures >= self._policy.failure_threshold:
                    exponent = state.failures - self._policy.failure_threshold
                    delay = min(self._policy.max_delay_seconds, self._policy.base_delay_seconds * (2**exponent))
                    state.blocked_until = now + delay
                self._states[key] = state

    def record_success(self, account_key: str, source_key: str) -> None:
        with self._lock:
            for key in _keys(account_key, source_key):
                self._states.pop(key, None)


class SQLiteAuthenticationRateLimiter:
    """Durable/shared authentication throttling using UTC wall-clock timestamps."""

    def __init__(
        self,
        database: SQLiteDatabase,
        policy: RateLimitPolicy = RateLimitPolicy(),
        clock=datetime.now,
    ) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database
        self._policy = policy
        self._clock = clock

    def allow(self, account_key: str, source_key: str) -> bool:
        now = _aware_now(self._clock)
        hashes = _keys(account_key, source_key)
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT blocked_until FROM auth_throttle_state WHERE throttle_key_hash IN (?, ?)",
                hashes,
            ).fetchall()
        return all(datetime_from_storage(row["blocked_until"]) <= now for row in rows)

    def record_failure(self, account_key: str, source_key: str) -> None:
        now = _aware_now(self._clock)
        with self._database.transaction() as connection:
            for key in _keys(account_key, source_key):
                row = connection.execute(
                    "SELECT failures, first_failure_at FROM auth_throttle_state WHERE throttle_key_hash = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    failures = 1
                    first_failure_at = now
                else:
                    first_failure_at = datetime_from_storage(row["first_failure_at"])
                    if (now - first_failure_at).total_seconds() > self._policy.window_seconds:
                        failures = 1
                        first_failure_at = now
                    else:
                        failures = int(row["failures"]) + 1
                delay = 0.0
                if failures >= self._policy.failure_threshold:
                    exponent = failures - self._policy.failure_threshold
                    delay = min(self._policy.max_delay_seconds, self._policy.base_delay_seconds * (2**exponent))
                blocked = datetime.fromtimestamp(now.timestamp() + delay, tz=timezone.utc)
                connection.execute(
                    """
                    INSERT INTO auth_throttle_state(throttle_key_hash, failures, first_failure_at, blocked_until, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(throttle_key_hash) DO UPDATE SET
                        failures=excluded.failures,
                        first_failure_at=excluded.first_failure_at,
                        blocked_until=excluded.blocked_until,
                        updated_at=excluded.updated_at
                    """,
                    (key, failures, datetime_to_storage(first_failure_at), datetime_to_storage(blocked), datetime_to_storage(now)),
                )

    def record_success(self, account_key: str, source_key: str) -> None:
        with self._database.transaction() as connection:
            connection.executemany(
                "DELETE FROM auth_throttle_state WHERE throttle_key_hash = ?",
                ((key,) for key in _keys(account_key, source_key)),
            )


def _keys(account_key: str, source_key: str) -> tuple[str, str]:
    return (_digest("account:" + account_key), _digest("source:" + source_key))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware_now(clock) -> datetime:
    try:
        value = clock(timezone.utc)
    except TypeError:
        value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
