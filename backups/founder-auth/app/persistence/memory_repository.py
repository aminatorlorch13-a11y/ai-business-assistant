from __future__ import annotations

import sqlite3

from app.models.memory import Memory
from app.persistence.database import SQLiteDatabase


class SQLiteMemoryRepository:
    """Durable implementation of the existing MemoryRepository contract."""

    MAX_ID_LENGTH = 128

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, memory: Memory) -> Memory:
        if not isinstance(memory, Memory):
            raise TypeError("memory must be a Memory.")
        self._validate_id(memory.memory_id)
        self._validate_id(memory.business_id)
        with self._database.connection() as connection:
            try:
                connection.execute(
                    """INSERT INTO memories(memory_id, business_id, content, memory_type, importance)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(memory_id) DO UPDATE SET
                         business_id=excluded.business_id, content=excluded.content,
                         memory_type=excluded.memory_type, importance=excluded.importance""",
                    (memory.memory_id, memory.business_id, memory.content, memory.memory_type, memory.importance),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("business_id does not reference an existing business.") from exc
        return memory

    def get(self, memory_id: str) -> Memory | None:
        self._validate_id(memory_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT memory_id, business_id, content, memory_type, importance FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return Memory(**dict(row)) if row else None

    def list_for_business(self, business_id: str) -> list[Memory]:
        self._validate_id(business_id)
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT memory_id, business_id, content, memory_type, importance FROM memories WHERE business_id = ? ORDER BY memory_id",
                (business_id,),
            ).fetchall()
        return [Memory(**dict(row)) for row in rows]

    def delete(self, memory_id: str) -> bool:
        self._validate_id(memory_id)
        with self._database.connection() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
        return cursor.rowcount == 1

    @classmethod
    def _validate_id(cls, value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("identifier must be a non-empty string.")
        if len(value) > cls.MAX_ID_LENGTH:
            raise ValueError("identifier exceeds the maximum allowed length.")
