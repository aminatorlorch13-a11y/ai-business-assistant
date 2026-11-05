"""Tenant-scoped persistent storage for Forge projects."""
import sqlite3
from datetime import datetime, timedelta, timezone

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import (
    datetime_from_storage,
    datetime_to_storage,
)
from app.forge.project import ForgeProject, ProjectStatus


class ProjectAlreadyExistsError(ValueError):
    """Raised when a project ID already exists for a business."""


class ProjectNotFoundError(LookupError):
    """Raised when a requested project does not exist."""


class ForgeProjectStore:
    MAX_ID_LENGTH = 128
    MAX_NAME_LENGTH = 160
    MAX_DESCRIPTION_LENGTH = 4000

    def __init__(self, database: SQLiteDatabase):
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def create(
        self,
        business_id: str,
        project_id: str,
        name: str,
        description: str = "",
    ) -> ForgeProject:
        business_id = self._validate_id(business_id, "business_id")
        project_id = self._validate_id(project_id, "project_id")
        name = self._validate_text(name, "name", self.MAX_NAME_LENGTH)
        description = self._validate_text(
            description, "description", self.MAX_DESCRIPTION_LENGTH,
            allow_empty=True,
        )

        now = datetime.now(timezone.utc)
        stored_now = datetime_to_storage(now)

        try:
            with self._database.transaction() as connection:
                business = connection.execute(
                    "SELECT 1 FROM businesses WHERE business_id = ?",
                    (business_id,),
                ).fetchone()
                if business is None:
                    raise ValueError("An existing business is required.")

                existing = connection.execute(
                    """
                    SELECT 1 FROM forge_projects
                    WHERE business_id = ? AND project_id = ?
                    """,
                    (business_id, project_id),
                ).fetchone()
                if existing is not None:
                    raise ProjectAlreadyExistsError(
                        "This project ID already exists for this business."
                    )

                connection.execute(
                    """
                    INSERT INTO forge_projects (
                        business_id, project_id, name, description,
                        status, created_at, updated_at, legacy_imported
                    ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, 0)
                    """,
                    (
                        business_id, project_id, name, description,
                        stored_now, stored_now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "The project could not be created because a database "
                "constraint was not satisfied."
            ) from exc

        return self.get(business_id, project_id)

    def get(self, business_id: str, project_id: str):
        business_id = self._validate_id(business_id, "business_id")
        project_id = self._validate_id(project_id, "project_id")
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_for_business(
        self,
        business_id: str,
        *,
        active_only: bool = False,
    ) -> list[ForgeProject]:
        business_id = self._validate_id(business_id, "business_id")
        if not isinstance(active_only, bool):
            raise TypeError("active_only must be a boolean.")

        query = """
            SELECT * FROM forge_projects
            WHERE business_id = ?
        """
        parameters = [business_id]
        if active_only:
            query += " AND status = 'ACTIVE'"
        query += " ORDER BY updated_at DESC, project_id ASC"

        with self._database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._from_row(row) for row in rows]

    def update(
        self,
        business_id: str,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> ForgeProject:
        business_id = self._validate_id(business_id, "business_id")
        project_id = self._validate_id(project_id, "project_id")

        if name is None and description is None:
            raise ValueError("at least one project field must be supplied.")

        if name is not None:
            name = self._validate_text(name, "name", self.MAX_NAME_LENGTH)
        if description is not None:
            description = self._validate_text(
                description, "description", self.MAX_DESCRIPTION_LENGTH,
                allow_empty=True,
            )

        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError("Project not found.")

            if row["status"] != ProjectStatus.ACTIVE.value:
                raise ValueError("Archived projects cannot be updated.")

            new_name = row["name"] if name is None else name
            new_description = (
                row["description"] if description is None else description
            )
            updated_at = self._next_timestamp(row["updated_at"])

            connection.execute(
                """
                UPDATE forge_projects
                SET name = ?, description = ?, updated_at = ?
                WHERE business_id = ? AND project_id = ?
                """,
                (
                    new_name, new_description, updated_at,
                    business_id, project_id,
                ),
            )

        return self.get(business_id, project_id)

    def archive(self, business_id: str, project_id: str) -> ForgeProject:
        business_id = self._validate_id(business_id, "business_id")
        project_id = self._validate_id(project_id, "project_id")

        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()

            if row is None:
                raise ProjectNotFoundError("Project not found.")

            if row["status"] != ProjectStatus.ARCHIVED.value:
                updated_at = self._next_timestamp(row["updated_at"])
                connection.execute(
                    """
                    UPDATE forge_projects
                    SET status = 'ARCHIVED', updated_at = ?
                    WHERE business_id = ? AND project_id = ?
                    """,
                    (updated_at, business_id, project_id),
                )

        return self.get(business_id, project_id)

    @staticmethod
    def _next_timestamp(previous: str) -> str:
        previous_time = datetime_from_storage(previous)
        now = datetime.now(timezone.utc)
        if now <= previous_time:
            now = previous_time + timedelta(microseconds=1)
        return datetime_to_storage(now)

    @staticmethod
    def _validate_id(value: str, field: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field} must be a string.")
        if not value or not value.strip():
            raise ValueError(f"{field} must not be empty.")
        if len(value) > ForgeProjectStore.MAX_ID_LENGTH:
            raise ValueError(f"{field} is too long.")
        if value != value.strip():
            raise ValueError(f"{field} must not contain outer whitespace.")
        return value

    @staticmethod
    def _validate_text(
        value: str,
        field: str,
        maximum: int,
        *,
        allow_empty: bool = False,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field} must be a string.")
        if not allow_empty and not value.strip():
            raise ValueError(f"{field} must not be empty.")
        if len(value) > maximum:
            raise ValueError(f"{field} exceeds its maximum length.")
        if value != value.strip():
            raise ValueError(f"{field} must not contain outer whitespace.")
        return value

    @staticmethod
    def _from_row(row) -> ForgeProject:
        try:
            return ForgeProject(
                business_id=row["business_id"],
                project_id=row["project_id"],
                name=row["name"],
                description=row["description"],
                status=ProjectStatus(row["status"]),
                created_at=datetime_from_storage(row["created_at"]),
                updated_at=datetime_from_storage(row["updated_at"]),
                legacy_imported=bool(row["legacy_imported"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Stored Forge project data is invalid.") from exc
