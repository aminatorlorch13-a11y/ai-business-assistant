from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UserRole(str, Enum):
    """Role granted to a user within one business tenant."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class SessionScope(str, Enum):
    """Authorization scope represented by an authenticated session."""

    BUSINESS = "business"
    PLATFORM = "platform"


@dataclass(frozen=True)
class User:
    user_id: str
    display_name: str
    email: str

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id must not be empty.")
        if not self.display_name:
            raise ValueError("display_name must not be empty.")
        if not self.email:
            raise ValueError("email must not be empty.")


@dataclass(frozen=True)
class BusinessMembership:
    user_id: str
    business_id: str
    role: UserRole

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id must not be empty.")
        if not self.business_id:
            raise ValueError("business_id must not be empty.")
        if not isinstance(self.role, UserRole):
            raise TypeError("role must be a UserRole.")


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Trusted identity presented to application authorization boundaries.

    BUSINESS sessions carry a business_id and customer UserRole.
    PLATFORM sessions carry neither because they represent platform-level
    authority rather than authority inside a customer tenant.

    Passwords, access tokens, refresh tokens, provider credentials, and other
    secrets must never be stored here.
    """

    user_id: str
    business_id: str | None
    role: UserRole | None
    session_id: str
    scope: SessionScope = SessionScope.BUSINESS

    def __post_init__(self) -> None:
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id must not be empty or whitespace.")

        if not isinstance(self.scope, SessionScope):
            raise TypeError("scope must be a SessionScope.")

        if not self.session_id or not self.session_id.strip():
            raise ValueError("session_id must not be empty or whitespace.")

        if self.scope is SessionScope.BUSINESS:
            if not self.business_id or not self.business_id.strip():
                raise ValueError(
                    "business_id is required and must not be whitespace "
                    "for a BUSINESS session."
                )

            if not isinstance(self.role, UserRole):
                raise TypeError(
                    "role must be a UserRole for a BUSINESS session."
                )

            return

        if self.scope is SessionScope.PLATFORM:
            if self.business_id is not None:
                raise ValueError(
                    "business_id must be None for a PLATFORM session."
                )

            if self.role is not None:
                raise ValueError(
                    "role must be None for a PLATFORM session."
                )
