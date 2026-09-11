from __future__ import annotations

from app.commercial.launch import LaunchProgram
from app.persistence.database import SQLiteDatabase


class SQLiteLaunchProgramRepository:
    """Durable repository for launch-program accounting."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def get(self) -> LaunchProgram:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT target_businesses, paid_businesses FROM launch_program WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("launch_program state is missing.")
        return LaunchProgram(row["target_businesses"], row["paid_businesses"])

    def set_target(self, target_businesses: int) -> LaunchProgram:
        current = self.get()
        updated = LaunchProgram(target_businesses, current.paid_businesses)
        with self._database.connection() as connection:
            connection.execute(
                "UPDATE launch_program SET target_businesses = ? WHERE singleton_id = 1",
                (updated.target_businesses,),
            )
        return updated
