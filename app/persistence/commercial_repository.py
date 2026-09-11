from __future__ import annotations

import sqlite3
from decimal import Decimal

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage


class SQLitePurchaseStore:
    """Durable purchase history repository with database uniqueness."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def get(self, provider: str, provider_event_id: str) -> PurchaseRecord | None:
        _validate(provider, provider_event_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM purchase_records WHERE provider = ? AND provider_event_id = ?",
                (provider, provider_event_id),
            ).fetchone()
        return _from_row(row) if row else None

    def save(self, record: PurchaseRecord) -> None:
        if not isinstance(record, PurchaseRecord):
            raise TypeError("record must be a PurchaseRecord.")
        with self._database.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO purchase_records(provider, provider_event_id, business_id, amount, currency, paid_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (record.provider, record.provider_event_id, record.business_id, str(record.purchase.amount),
                     record.purchase.currency, record.purchase.paid_at.isoformat(), record.recorded_at.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Purchase record cannot be persisted.") from exc


def _from_row(row) -> PurchaseRecord:
    purchase = VerifiedPurchase(
        provider=row["provider"], provider_event_id=row["provider_event_id"], business_id=row["business_id"],
        amount=Decimal(row["amount"]), currency=row["currency"], paid_at=datetime_from_storage(row["paid_at"]),
    )
    return PurchaseRecord(purchase=purchase, recorded_at=datetime_from_storage(row["recorded_at"]))


def _validate(provider: object, event_id: object) -> None:
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("provider must be a non-empty string.")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("provider_event_id must be a non-empty string.")
