from __future__ import annotations

import sqlite3

from app.commercial.purchase_record import PurchaseRecord
from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage


class SQLiteCommercialTransaction:
    """Database transaction implementing the existing commercial contract."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database
        self._connection_context = database.connection()
        self._connection = self._connection_context.__enter__()
        self._completed = False
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except Exception:
            self._connection_context.__exit__(*__import__("sys").exc_info())
            self._connection = None
            self._completed = True
            raise

    def _ensure_open(self) -> sqlite3.Connection:
        if self._completed or self._connection is None:
            raise RuntimeError("Transaction is already completed.")
        return self._connection

    def record_purchase_once(self, record: PurchaseRecord) -> bool:
        connection = self._ensure_open()
        if not isinstance(record, PurchaseRecord):
            raise TypeError("record must be a PurchaseRecord.")
        try:
            connection.execute(
                "INSERT INTO purchase_records(provider, provider_event_id, business_id, amount, currency, paid_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.provider, record.provider_event_id, record.business_id, str(record.purchase.amount),
                 record.purchase.currency, datetime_to_storage(record.purchase.paid_at),
                 datetime_to_storage(record.recorded_at)),
            )
            return True
        except sqlite3.IntegrityError:
            exists = connection.execute(
                "SELECT 1 FROM purchase_records WHERE provider = ? AND provider_event_id = ?",
                (record.provider, record.provider_event_id),
            ).fetchone()
            if exists is not None:
                return False
            raise ValueError("Verified purchase cannot be persisted.")

    def activate_business(self, business_id: str) -> None:
        connection = self._ensure_open()
        _validate_id(business_id)
        if connection.execute("SELECT 1 FROM businesses WHERE business_id = ?", (business_id,)).fetchone() is None:
            raise ValueError("business_id does not reference an existing business.")
        connection.execute(
            "INSERT INTO commercial_states(business_id, status) VALUES (?, 'active') ON CONFLICT(business_id) DO UPDATE SET status='active'",
            (business_id,),
        )

    def record_paid_business(self, business_id: str) -> None:
        connection = self._ensure_open()
        _validate_id(business_id)
        if connection.execute("SELECT 1 FROM businesses WHERE business_id = ?", (business_id,)).fetchone() is None:
            raise ValueError("business_id does not reference an existing business.")
        inserted = connection.execute(
            "INSERT OR IGNORE INTO paid_business_ledger(business_id) VALUES (?)",
            (business_id,),
        ).rowcount
        if inserted == 1:
            connection.execute(
                "UPDATE launch_program SET paid_businesses = MIN(target_businesses, paid_businesses + 1) WHERE singleton_id = 1"
            )

    def commit(self) -> None:
        connection = self._ensure_open()
        try:
            connection.commit()
        finally:
            self._close()

    def rollback(self) -> None:
        connection = self._ensure_open()
        try:
            connection.rollback()
        finally:
            self._close()

    def has_purchase(self, provider: str, provider_event_id: str) -> bool:
        connection = self._ensure_open()
        _validate_id(provider)
        _validate_id(provider_event_id)
        return connection.execute(
            "SELECT 1 FROM purchase_records WHERE provider = ? AND provider_event_id = ?",
            (provider, provider_event_id),
        ).fetchone() is not None

    def is_business_active(self, business_id: str) -> bool:
        connection = self._ensure_open()
        _validate_id(business_id)
        return connection.execute(
            "SELECT 1 FROM commercial_states WHERE business_id = ? AND status = 'active'",
            (business_id,),
        ).fetchone() is not None

    def is_paid_business(self, business_id: str) -> bool:
        connection = self._ensure_open()
        _validate_id(business_id)
        return connection.execute(
            "SELECT 1 FROM paid_business_ledger WHERE business_id = ?",
            (business_id,),
        ).fetchone() is not None

    def _close(self) -> None:
        if self._completed:
            return
        self._completed = True
        self._connection = None
        self._connection_context.__exit__(None, None, None)


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
