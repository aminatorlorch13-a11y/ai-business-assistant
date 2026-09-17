from __future__ import annotations

from app.founder.models import FounderRecord
from app.identity.models import AuthenticatedPrincipal
from app.persistence.founder_repository import SQLiteFounderRepository


class FounderAccessDenied(PermissionError):
    """Raised when an authenticated principal lacks Founder authority."""


class FounderAuthorizationService:
    """Authorizes platform-level Founder access independently of tenant roles."""

    def __init__(self, founders: SQLiteFounderRepository) -> None:
        self._founders = founders

    def resolve(
        self,
        principal: AuthenticatedPrincipal,
    ) -> FounderRecord | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        founder = self._founders.get(principal.user_id)

        if founder is None or not founder.active:
            return None

        return founder

    def require_founder(
        self,
        principal: AuthenticatedPrincipal,
    ) -> FounderRecord:
        founder = self.resolve(principal)

        if founder is None:
            raise FounderAccessDenied("Founder access is required.")

        return founder
