from __future__ import annotations

from app.persistence.commercial_transaction import SQLiteCommercialTransaction
from app.persistence.database import SQLiteDatabase


class SQLiteCommercialTransactionFactory:
    """Create fresh durable commercial transactions."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def begin(self) -> SQLiteCommercialTransaction:
        return SQLiteCommercialTransaction(self._database)
