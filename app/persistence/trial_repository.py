from __future__ import annotations

from datetime import datetime

from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage, datetime_to_storage


class SQLiteTrialRepository:
    """Durable repository for one business's commercial trial start."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, trial: BusinessTrial) -> BusinessTrial:
        if not isinstance(trial, BusinessTrial):
            raise TypeError("trial must be a BusinessTrial.")
        with self._database.connection() as connection:
            connection.execute(
                "INSERT INTO business_trials(business_id, started_at) VALUES (?, ?) ON CONFLICT(business_id) DO UPDATE SET started_at=excluded.started_at",
                (trial.business_id, datetime_to_storage(trial.started_at)),
            )
        return trial

    def get(self, business_id: str) -> BusinessTrial | None:
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT business_id, started_at FROM business_trials WHERE business_id = ?",
                (business_id,),
            ).fetchone()
        return BusinessTrial(row["business_id"], datetime_from_storage(row["started_at"])) if row else None
