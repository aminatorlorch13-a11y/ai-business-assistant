from __future__ import annotations

from app.identity.models import BusinessMembership, UserRole
from app.persistence.database import SQLiteDatabase


class SQLiteMembershipRepository:
    """Durable user-to-business authorization membership repository."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, membership: BusinessMembership) -> BusinessMembership:
        if not isinstance(membership, BusinessMembership):
            raise TypeError("membership must be a BusinessMembership.")
        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO business_memberships(user_id, business_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, business_id) DO UPDATE SET role=excluded.role
                """,
                (membership.user_id, membership.business_id, membership.role.value),
            )
        return membership

    def get(self, user_id: str, business_id: str) -> BusinessMembership | None:
        _validate_id(user_id)
        _validate_id(business_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT user_id, business_id, role FROM business_memberships WHERE user_id = ? AND business_id = ?",
                (user_id, business_id),
            ).fetchone()
        if row is None:
            return None
        return BusinessMembership(row["user_id"], row["business_id"], UserRole(row["role"]))

    def list_for_user(self, user_id: str) -> list[BusinessMembership]:
        _validate_id(user_id)
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT user_id, business_id, role FROM business_memberships WHERE user_id = ? ORDER BY business_id",
                (user_id,),
            ).fetchall()
        return [BusinessMembership(r["user_id"], r["business_id"], UserRole(r["role"])) for r in rows]

    def list_for_business(self, business_id: str) -> list[BusinessMembership]:
        _validate_id(business_id)
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT user_id, business_id, role FROM business_memberships WHERE business_id = ? ORDER BY user_id",
                (business_id,),
            ).fetchall()
        return [BusinessMembership(r["user_id"], r["business_id"], UserRole(r["role"])) for r in rows]


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
