from __future__ import annotations


class AuthenticationError(Exception):
    """Generic authentication failure exposed to callers."""

    def __init__(self, message: str = "Authentication failed.") -> None:
        super().__init__(message)


class AuthenticationRateLimited(AuthenticationError):
    """Authentication was temporarily throttled."""


class BusinessSelectionRequired(AuthenticationError):
    """Valid credentials require explicit business selection."""

    def __init__(self, memberships: tuple[tuple[str, str, str], ...]) -> None:
        super().__init__("Business selection is required.")
        self.memberships = memberships


class SessionInvalid(AuthenticationError):
    """Session is missing, expired, or revoked."""
