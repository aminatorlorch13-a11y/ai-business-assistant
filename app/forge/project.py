"""Forge project domain model."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class ForgeProject:
    business_id: str
    project_id: str
    name: str
    description: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    legacy_imported: bool = False
