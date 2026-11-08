"""Tenant-scoped, immutable GitHub repository registration."""

import re
import sqlite3
from datetime import datetime, timezone

from app.forge.project import ProjectStatus
from app.forge.project_repository import ForgeProjectRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import (
    datetime_from_storage,
    datetime_to_storage,
)


class RepositoryAlreadyBoundError(ValueError):
    """Raised when a Forge project already has a repository binding."""


class ForgeProjectRepositoryStore:
    MAX_ID_LENGTH = 128
    _OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
    _REPOSITORY = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
    _FORBIDDEN_BRANCH_CHARS = set(" ~^:?*[\\")

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def register(
        self,
        business_id: str,
        project_id: str,
        repository_owner: str,
        repository_name: str,
        *,
        default_branch: str = "main",
    ) -> ForgeProjectRepository:
        business_id = self._validate_id(business_id, "business_id")
        project_id = self._validate_id(project_id, "project_id")
        repository_owner = self._validate_owner(repository_owner)
        repository_name = self._validate_repository(repository_name)
        default_branch = self._validate_branch(default_branch)

        now = datetime_to_storage(datetime.now(timezone.utc))
        try:
            with self._database.transaction() as connection:
                project = connection.execute(
                    """
                    SELECT status FROM forge_projects
                    WHERE business_id = ? AND project_id = ?
                    """,
                    (business_id, project_id),
                ).fetchone()

                if project is None or project["status"] != ProjectStatus.ACTIVE.value:
                    raise ValueError("An existing active Forge project is required.")

                existing = connection.execute(
                    """
                    SELECT 1 FROM forge_project_repositories
                    WHERE business_id = ? AND project_id = ?
                    """,
                    (business_id, project_id),
                ).fetchone()
                if existing is not None:
                    raise RepositoryAlreadyBoundError(
                        "This Forge project already has a repository binding."
                    )

                connection.execute(
                    """
                    INSERT INTO forge_project_repositories (
                        business_id, project_id, provider, repository_owner,
                        repository_name, default_branch, created_at, updated_at
                    ) VALUES (?, ?, 'github', ?, ?, ?, ?, ?)
                    """,
                    (
                        business_id,
                        project_id,
                        repository_owner,
                        repository_name,
                        default_branch,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "Repository registration failed a database constraint."
            ) from exc

        result = self.get(business_id, project_id)
        if result is None:
            raise RuntimeError("Repository registration was not persisted.")
        return result

    def get(
        self,
        business_id: str,
        project_id: str,
    ) -> ForgeProjectRepository | None:
        business_id = self._validate_id(business_id, "business_id")
        project_id = self._validate_id(project_id, "project_id")

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM forge_project_repositories
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()
        return None if row is None else self._from_row(row)

    @classmethod
    def _validate_id(cls, value: str, field: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field} must be a string.")
        if not value or value != value.strip():
            raise ValueError(f"{field} must be non-empty without outer whitespace.")
        if len(value) > cls.MAX_ID_LENGTH:
            raise ValueError(f"{field} is too long.")
        return value

    @classmethod
    def _validate_owner(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("repository_owner must be a string.")
        if not cls._OWNER.fullmatch(value):
            raise ValueError("repository_owner is not a valid GitHub owner.")
        return value

    @classmethod
    def _validate_repository(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("repository_name must be a string.")
        if (
            not cls._REPOSITORY.fullmatch(value)
            or value in {".", ".."}
            or value.endswith(".")
        ):
            raise ValueError("repository_name is not a valid GitHub repository name.")
        return value

    @classmethod
    def _validate_branch(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("default_branch must be a string.")
        if (
            not value
            or len(value) > 255
            or value.startswith("/")
            or value.endswith(("/", "."))
            or "//" in value
            or ".." in value
            or "@{" in value
            or value in {"@", "HEAD"}
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(char in cls._FORBIDDEN_BRANCH_CHARS for char in value)
        ):
            raise ValueError("default_branch is not a safe Git branch name.")

        segments = value.split("/")
        if any(
            not segment
            or segment.startswith(".")
            or segment.startswith("-")
            or segment.endswith(".lock")
            for segment in segments
        ):
            raise ValueError("default_branch contains an unsafe Git ref component.")
        return value

    @staticmethod
    def _from_row(row) -> ForgeProjectRepository:
        try:
            return ForgeProjectRepository(
                business_id=row["business_id"],
                project_id=row["project_id"],
                provider=row["provider"],
                repository_owner=row["repository_owner"],
                repository_name=row["repository_name"],
                default_branch=row["default_branch"],
                created_at=datetime_from_storage(row["created_at"]),
                updated_at=datetime_from_storage(row["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Stored Forge repository binding is invalid.") from exc
