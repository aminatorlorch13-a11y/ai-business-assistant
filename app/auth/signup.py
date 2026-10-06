from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from app.auth.passwords import ScryptPasswordHasher
from app.commercial.state import CommercialStatus
from app.identity.models import BusinessMembership, User, UserRole
from app.models.business import Business
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage


class SignupConflict(ValueError):
    """Signup conflicts with an existing durable identity."""


class SQLiteSignupTransaction:
    """Atomic registration of user, business, membership, credential and trial."""

    def __init__(self, database: SQLiteDatabase, password_hasher: ScryptPasswordHasher | None = None, clock: Callable[..., datetime] = datetime.now) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database
        self._password_hasher = password_hasher or ScryptPasswordHasher()
        self._clock = clock

    def signup(
        self,
        *,
        display_name: str,
        email: str,
        password: str,
        business_name: str,
        assistant_name: str,
        assistant_voice: str,
        business_id: str | None = None,
        user_id: str | None = None,
    ) -> tuple[User, Business, BusinessMembership, datetime]:
        normalized_email = _normalize_email(email)
        _required(display_name, "display_name")
        _required(business_name, "business_name")
        _required(assistant_name, "assistant_name")
        _required(assistant_voice, "assistant_voice")
        credential_hash = self._password_hasher.hash(password)
        now = _aware_now(self._clock)
        user = User(user_id or _new_id("user"), display_name.strip(), normalized_email)
        business = Business(
            business_id or _new_id("business"),
            business_name.strip(),
            display_name.strip(),
            assistant_name.strip(),
            assistant_voice.strip().lower(),
        )
        membership = BusinessMembership(user.user_id, business.business_id, UserRole.OWNER)

        with self._database.transaction() as connection:
            if connection.execute("SELECT 1 FROM users WHERE email = ?", (normalized_email,)).fetchone() is not None:
                raise SignupConflict("An account already exists for that email.")
            if connection.execute("SELECT 1 FROM businesses WHERE business_id = ?", (business.business_id,)).fetchone() is not None:
                raise SignupConflict("The generated business identifier already exists.")

            connection.execute(
                "INSERT INTO users(user_id, display_name, email) VALUES (?, ?, ?)",
                (user.user_id, user.display_name, user.email),
            )
            connection.execute(
                "INSERT INTO businesses(business_id, name, owner_name, assistant_name, assistant_voice) VALUES (?, ?, ?, ?, ?)",
                (business.business_id, business.name, business.owner_name, business.assistant_name, business.assistant_voice),
            )
            connection.execute(
                "INSERT INTO business_memberships(user_id, business_id, role) VALUES (?, ?, ?)",
                (membership.user_id, membership.business_id, membership.role.value),
            )
            connection.execute(
                "INSERT INTO credentials(user_id, credential_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (user.user_id, credential_hash, datetime_to_storage(now), datetime_to_storage(now)),
            )
            connection.execute(
                "INSERT INTO business_trials(business_id, started_at) VALUES (?, ?)",
                (business.business_id, datetime_to_storage(now)),
            )
            connection.execute(
                '''
                INSERT INTO business_capability_entitlements(
                    business_id,
                    configured_at
                )
                VALUES (?, ?)
                ''',
                (
                    business.business_id,
                    datetime_to_storage(now),
                ),
            )

            connection.execute(
                '''
                INSERT INTO business_capability_grants(
                    business_id,
                    capability
                )
                VALUES (?, ?)
                ''',
                (
                    business.business_id,
                    "memory",
                ),
            )

            connection.execute(
                "INSERT INTO commercial_states(business_id, status) VALUES (?, ?)",
                (business.business_id, CommercialStatus.TRIAL.value),
            )

        return user, business, membership, now


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("email must be a string.")
    value = email.strip().casefold()
    if not value or len(value) > 320 or "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("email must have a valid basic structure.")
    return value


def _required(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")


def _aware_now(clock) -> datetime:
    try:
        value = clock(timezone.utc)
    except TypeError:
        value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
