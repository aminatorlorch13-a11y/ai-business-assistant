"""GitHub repository identity bound to a Forge project."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ForgeProjectRepository:
    business_id: str
    project_id: str
    provider: str
    repository_owner: str
    repository_name: str
    default_branch: str
    created_at: datetime
    updated_at: datetime

    @property
    def clone_url(self) -> str:
        """Return the canonical HTTPS URL; this does not perform a clone."""
        return (
            f"https://github.com/{self.repository_owner}/"
            f"{self.repository_name}.git"
        )
