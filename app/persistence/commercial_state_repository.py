from __future__ import annotations

from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.persistence.database import SQLiteDatabase


class SQLiteCommercialStateRepository:
    """Durable repository for business commercial lifecycle state."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, state: BusinessCommercialState) -> BusinessCommercialState:
        if not isinstance(state, BusinessCommercialState):
            raise TypeError("state must be a BusinessCommercialState.")
        with self._database.connection() as connection:
            connection.execute(
                "INSERT INTO commercial_states(business_id, status) VALUES (?, ?) ON CONFLICT(business_id) DO UPDATE SET status=excluded.status",
                (state.business_id, state.status.value),
            )
        return state

    def get(self, business_id: str) -> BusinessCommercialState | None:
        _validate_id(business_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT business_id, status FROM commercial_states WHERE business_id = ?",
                (business_id,),
            ).fetchone()
        return BusinessCommercialState(row["business_id"], CommercialStatus(row["status"])) if row else None


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
