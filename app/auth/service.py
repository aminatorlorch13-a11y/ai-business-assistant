from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.auth.errors import (
    AuthenticationError,
    AuthenticationRateLimited,
    BusinessSelectionRequired,
    SessionInvalid,
)
from app.auth.passwords import ScryptPasswordHasher
from app.auth.rate_limit import (
    InMemoryAuthenticationRateLimiter,
)
from app.founder.models import FounderRecord
from app.identity.models import (
    AuthenticatedPrincipal,
    SessionScope,
    UserRole,
)
from app.persistence.session import SessionRecord


SESSION_LIFETIME = timedelta(hours=12)


class CredentialStore(Protocol):
    def get_by_user_id(self, user_id: str): ...

    def save(self, user_id: str, credential_hash: str): ...


class AuthenticationUserStore(Protocol):
    def get_by_email(self, email: str): ...

    def get(self, user_id: str): ...


class AuthenticationMembershipStore(Protocol):
    def get(self, user_id: str, business_id: str): ...

    def list_for_user(self, user_id: str): ...


class AuthenticationFounderStore(Protocol):
    def get(self, user_id: str) -> FounderRecord | None: ...


class AuthenticationSessionStore(Protocol):
    def save(self, session: SessionRecord): ...

    def get(self, session_id_hash: str): ...

    def revoke(self, session_id_hash: str, revoked_at: datetime): ...


class AuthenticationRateLimiter(Protocol):
    def allow(self, account_key: str, source_key: str) -> bool: ...

    def record_failure(
        self,
        account_key: str,
        source_key: str,
    ) -> None: ...

    def record_success(
        self,
        account_key: str,
        source_key: str,
    ) -> None: ...


class AuthenticationService:
    """Transport-neutral authentication boundary.

    Customer authentication creates BUSINESS-scoped sessions.

    Founder authentication creates PLATFORM-scoped sessions only after the
    authenticated user is confirmed against the authoritative Founder store.
    """

    def __init__(
        self,
        users: AuthenticationUserStore,
        credentials: CredentialStore,
        memberships: AuthenticationMembershipStore,
        sessions: AuthenticationSessionStore,
        password_hasher: ScryptPasswordHasher | None = None,
        rate_limiter: AuthenticationRateLimiter | None = None,
        session_lifetime: timedelta = SESSION_LIFETIME,
        clock=datetime.now,
        founders: AuthenticationFounderStore | None = None,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._memberships = memberships
        self._sessions = sessions
        self._founders = founders
        self._password_hasher = (
            password_hasher or ScryptPasswordHasher()
        )
        self._rate_limiter = (
            rate_limiter or InMemoryAuthenticationRateLimiter()
        )
        self._session_lifetime = session_lifetime
        self._clock = clock

        # One expensive dummy hash makes unknown-account paths exercise the
        # same password-verification primitive without storing a real
        # user's password.
        self._dummy_credential_hash = self._password_hasher.hash(
            secrets.token_urlsafe(32)
        )

    def login(
        self,
        email: str,
        password: str,
        *,
        business_id: str | None = None,
        source_key: str = "unknown",
    ) -> AuthenticatedPrincipal:
        """Authenticate a customer and create a BUSINESS session."""

        normalized_email = _normalize_email(email)

        if not self._rate_limiter.allow(normalized_email, source_key):
            raise AuthenticationRateLimited()

        user = self._users.get_by_email(normalized_email)
        credential_hash = self._dummy_credential_hash

        if user is not None:
            credential = self._credentials.get_by_user_id(user.user_id)
            if credential is not None:
                credential_hash = credential.credential_hash

        password_valid = self._password_hasher.verify(
            password,
            credential_hash,
        )

        if user is None or not password_valid:
            self._record_failure(normalized_email, source_key)
            raise AuthenticationError()

        memberships = tuple(
            self._memberships.list_for_user(user.user_id)
        )

        if not memberships:
            self._record_failure(normalized_email, source_key)
            raise AuthenticationError()

        if business_id is None:
            if len(memberships) != 1:
                raise BusinessSelectionRequired(
                    tuple(
                        (
                            membership.business_id,
                            membership.role.value,
                            user.display_name,
                        )
                        for membership in memberships
                    )
                )
            membership = memberships[0]
        else:
            membership = self._memberships.get(
                user.user_id,
                business_id,
            )

            if membership is None:
                self._record_failure(normalized_email, source_key)
                raise AuthenticationError()

        self._rate_limiter.record_success(
            normalized_email,
            source_key,
        )

        return self._create_business_session(
            user.user_id,
            membership.business_id,
            membership.role,
        )

    def login_founder(
        self,
        email: str,
        password: str,
        *,
        source_key: str = "founder",
    ) -> AuthenticatedPrincipal:
        """Authenticate a platform Founder and create a PLATFORM session.

        Founder authority is independently persisted in the Founder store.
        A valid customer credential alone can never create a PLATFORM session.
        """

        normalized_email = _normalize_email(email)

        if not self._rate_limiter.allow(normalized_email, source_key):
            raise AuthenticationRateLimited()

        user = self._users.get_by_email(normalized_email)
        credential_hash = self._dummy_credential_hash

        if user is not None:
            credential = self._credentials.get_by_user_id(user.user_id)
            if credential is not None:
                credential_hash = credential.credential_hash

        password_valid = self._password_hasher.verify(
            password,
            credential_hash,
        )

        if user is None or not password_valid:
            self._record_failure(normalized_email, source_key)
            raise AuthenticationError()

        if self._founders is None:
            self._record_failure(normalized_email, source_key)
            raise AuthenticationError()

        founder = self._founders.get(user.user_id)

        if founder is None or not founder.active:
            self._record_failure(normalized_email, source_key)
            raise AuthenticationError()

        self._rate_limiter.record_success(
            normalized_email,
            source_key,
        )

        return self._create_platform_session(user.user_id)

    def validate_session(
        self,
        session_id: str,
    ) -> AuthenticatedPrincipal:
        """Validate an opaque session and reconstruct its trusted principal."""

        if not isinstance(session_id, str) or not session_id:
            raise SessionInvalid()

        session_hash = _hash_session_id(session_id)
        record = self._sessions.get(session_hash)

        if record is None or record.revoked_at is not None:
            raise SessionInvalid()

        now = _aware_now(self._clock)

        if record.expires_at <= now:
            self._sessions.revoke(session_hash, now)
            raise SessionInvalid()

        self._sessions.save(
            SessionRecord(
                session_id_hash=record.session_id_hash,
                user_id=record.user_id,
                scope=record.scope,
                business_id=record.business_id,
                role=record.role,
                created_at=record.created_at,
                expires_at=record.expires_at,
                last_seen_at=now,
                revoked_at=record.revoked_at,
            )
        )

        return AuthenticatedPrincipal(
            user_id=record.user_id,
            scope=record.scope,
            business_id=record.business_id,
            role=record.role,
            session_id=session_id,
        )

    def logout(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id:
            return

        now = _aware_now(self._clock)
        self._sessions.revoke(
            _hash_session_id(session_id),
            now,
        )

    def _create_business_session(
        self,
        user_id: str,
        business_id: str,
        role: UserRole,
    ) -> AuthenticatedPrincipal:
        now = _aware_now(self._clock)
        session_id = secrets.token_urlsafe(32)

        self._sessions.save(
            SessionRecord(
                session_id_hash=_hash_session_id(session_id),
                user_id=user_id,
                scope=SessionScope.BUSINESS,
                business_id=business_id,
                role=role,
                created_at=now,
                expires_at=now + self._session_lifetime,
                last_seen_at=now,
            )
        )

        return AuthenticatedPrincipal(
            user_id=user_id,
            scope=SessionScope.BUSINESS,
            business_id=business_id,
            role=role,
            session_id=session_id,
        )

    def _create_platform_session(
        self,
        user_id: str,
    ) -> AuthenticatedPrincipal:
        now = _aware_now(self._clock)
        session_id = secrets.token_urlsafe(32)

        self._sessions.save(
            SessionRecord(
                session_id_hash=_hash_session_id(session_id),
                user_id=user_id,
                scope=SessionScope.PLATFORM,
                business_id=None,
                role=None,
                created_at=now,
                expires_at=now + self._session_lifetime,
                last_seen_at=now,
            )
        )

        return AuthenticatedPrincipal(
            user_id=user_id,
            scope=SessionScope.PLATFORM,
            business_id=None,
            role=None,
            session_id=session_id,
        )

    def _record_failure(
        self,
        email: str,
        source_key: str,
    ) -> None:
        self._rate_limiter.record_failure(
            email,
            source_key,
        )


def _normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise AuthenticationError()

    value = email.strip().casefold()

    if (
        not value
        or len(value) > 320
        or "@" not in value
        or value.startswith("@")
        or value.endswith("@")
    ):
        raise AuthenticationError()

    return value


def _hash_session_id(session_id: str) -> str:
    return hashlib.sha256(
        session_id.encode("utf-8")
    ).hexdigest()


def _aware_now(clock) -> datetime:
    try:
        value = clock(timezone.utc)
    except TypeError:
        value = clock()

    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)
