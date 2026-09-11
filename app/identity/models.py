from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UserRole(str, Enum):
    """Role granted to a user within one business tenant."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True)
class User:
    """Identity record containing no authentication secrets."""

    user_id: str
    display_name: str
    email: str

    def __post_init__(self) -> None:
        for field_name, value in {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "email": self.email,
        }.items():
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string.")
            if not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")

        if "@" not in self.email or self.email.startswith("@") or self.email.endswith("@"):
            raise ValueError("email must contain a valid basic email structure.")


@dataclass(frozen=True)
class BusinessMembership:
    """A user's authorization role inside one business."""

    user_id: str
    business_id: str
    role: UserRole

    def __post_init__(self) -> None:
        for field_name, value in {
            "user_id": self.user_id,
            "business_id": self.business_id,
        }.items():
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string.")
            if not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")

        if not isinstance(self.role, UserRole):
            raise TypeError("role must be a UserRole.")


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Trusted identity presented to application authorization boundaries.

    This object deliberately contains identity and authorization context only.
    Passwords, access tokens, refresh tokens, provider credentials, and other
    secrets must never be stored here.
    """

    user_id: str
    business_id: str
    role: UserRole
    session_id: str

    def __post_init__(self) -> None:
        for field_name, value in {
            "user_id": self.user_id,
            "business_id": self.business_id,
            "session_id": self.session_id,
        }.items():
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string.")
            if not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")

        if not isinstance(self.role, UserRole):
            raise TypeError("role must be a UserRole.")
