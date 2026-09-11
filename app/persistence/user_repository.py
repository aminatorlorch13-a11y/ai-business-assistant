from __future__ import annotations

from app.identity.models import User
from app.persistence.database import SQLiteDatabase


class SQLiteUserRepository:
    """Durable identity repository; authentication secrets are separate."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, user: User) -> User:
        if not isinstance(user, User):
            raise TypeError("user must be a User.")
        with self._database.connection() as connection:
            connection.execute(
                """INSERT INTO users(user_id, display_name, email) VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     display_name=excluded.display_name, email=excluded.email""",
                (user.user_id, user.display_name, user.email),
            )
        return user

    def get(self, user_id: str) -> User | None:
        _validate_id(user_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT user_id, display_name, email FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return User(**dict(row)) if row else None

    def get_by_email(self, email: str) -> User | None:
        if not isinstance(email, str) or not email.strip():
            raise ValueError("email must be a non-empty string.")
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT user_id, display_name, email FROM users WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
        return User(**dict(row)) if row else None


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
