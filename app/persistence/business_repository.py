from __future__ import annotations

from app.models.business import Business
from app.persistence.database import SQLiteDatabase


class SQLiteBusinessRepository:
    """Durable repository for business configuration."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, business: Business) -> Business:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")
        with self._database.connection() as connection:
            connection.execute(
                """INSERT INTO businesses
                   (business_id, name, owner_name, assistant_name, assistant_voice)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(business_id) DO UPDATE SET
                     name=excluded.name, owner_name=excluded.owner_name,
                     assistant_name=excluded.assistant_name, assistant_voice=excluded.assistant_voice""",
                (business.business_id, business.name, business.owner_name,
                 business.assistant_name, business.assistant_voice),
            )
        return business

    def get(self, business_id: str) -> Business | None:
        _validate_id(business_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT business_id, name, owner_name, assistant_name, assistant_voice FROM businesses WHERE business_id = ?",
                (business_id,),
            ).fetchone()
        return Business(**dict(row)) if row else None


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
