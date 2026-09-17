from app.commercial.in_memory_commercial_store import (
    InMemoryCommercialStore,
)
from app.commercial.purchase_record import PurchaseRecord


class InMemoryCommercialTransaction:
    """
    In-memory implementation of the commercial transaction boundary.

    Committed state belongs to a shared InMemoryCommercialStore.

    Each transaction maintains private staged changes until commit().
    Therefore:

        transaction A
            ↓
        stage changes
            ↓
        commit
            ↓
        shared store
            ↓
        transaction B sees committed state

    rollback() discards only the current transaction's staged changes.

    This implementation models transaction semantics for deterministic
    testing. Production persistence must provide equivalent atomicity using
    a real database transaction and database-level constraints.
    """

    def __init__(
        self,
        store: InMemoryCommercialStore,
    ) -> None:
        if not isinstance(
            store,
            InMemoryCommercialStore,
        ):
            raise TypeError(
                "store must be an InMemoryCommercialStore."
            )

        self._store = store

        self._staged_purchase_records: dict[
            tuple[str, str],
            PurchaseRecord,
        ] = {}
        self._staged_active_businesses: set[str] = set()
        self._staged_paid_businesses: set[str] = set()

        self._completed = False

    @staticmethod
    def _purchase_key(
        record: PurchaseRecord,
    ) -> tuple[str, str]:
        if not isinstance(record, PurchaseRecord):
            raise TypeError(
                "record must be a PurchaseRecord."
            )

        return (
            record.provider,
            record.provider_event_id,
        )

    @staticmethod
    def _business_id(
        business_id: str,
    ) -> str:
        if not isinstance(business_id, str):
            raise TypeError(
                "business_id must be a string."
            )

        if not business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        return business_id

    def _ensure_open(self) -> None:
        if self._completed:
            raise RuntimeError(
                "Transaction is already completed."
            )

    def record_purchase_once(
        self,
        record: PurchaseRecord,
    ) -> bool:
        """
        Stage a purchase exactly once.

        Duplicate detection checks both shared committed state and
        purchases already staged by this transaction.
        """
        self._ensure_open()

        key = self._purchase_key(record)

        if self._store.has_purchase(
            record.provider,
            record.provider_event_id,
        ):
            return False

        if key in self._staged_purchase_records:
            return False

        self._staged_purchase_records[key] = record
        return True

    def activate_business(
        self,
        business_id: str,
    ) -> None:
        """
        Stage business activation.
        """
        self._ensure_open()

        business_id = self._business_id(
            business_id,
        )

        self._staged_active_businesses.add(
            business_id,
        )

    def record_paid_business(
        self,
        business_id: str,
    ) -> None:
        """
        Stage launch-program recognition of a paying business.
        """
        self._ensure_open()

        business_id = self._business_id(
            business_id,
        )

        self._staged_paid_businesses.add(
            business_id,
        )

    def commit(self) -> None:
        """Persist all staged changes atomically to the shared store.

        If any operation fails, restore the shared store to its exact
        pre-commit state and close the transaction.
        """
        self._ensure_open()

        purchase_records_snapshot = dict(self._store.purchase_records)
        active_businesses_snapshot = set(self._store.active_businesses)
        paid_businesses_snapshot = set(self._store.paid_businesses)

        try:
            for key, record in self._staged_purchase_records.items():
                self._store.add_purchase(record)

            for business_id in self._staged_active_businesses:
                self._store.activate_business(business_id)

            for business_id in self._staged_paid_businesses:
                self._store.record_paid_business(business_id)

        except Exception:
            self._store.purchase_records.clear()
            self._store.purchase_records.update(purchase_records_snapshot)

            self._store.active_businesses.clear()
            self._store.active_businesses.update(active_businesses_snapshot)

            self._store.paid_businesses.clear()
            self._store.paid_businesses.update(paid_businesses_snapshot)

            self._staged_purchase_records.clear()
            self._staged_active_businesses.clear()
            self._staged_paid_businesses.clear()
            self._completed = True
            raise

        self._staged_purchase_records.clear()
        self._staged_active_businesses.clear()
        self._staged_paid_businesses.clear()
        self._completed = True

    def rollback(self) -> None:
        """
        Discard all staged changes.
        """
        self._ensure_open()

        self._staged_purchase_records.clear()
        self._staged_active_businesses.clear()
        self._staged_paid_businesses.clear()

        self._completed = True

    def has_purchase(
        self,
        provider: str,
        provider_event_id: str,
    ) -> bool:
        """
        Return whether a purchase exists in shared committed state or
        this transaction's staged state.
        """
        if not isinstance(provider, str):
            raise TypeError(
                "provider must be a string."
            )

        if not provider.strip():
            raise ValueError(
                "provider must be a non-empty string."
            )

        if not isinstance(provider_event_id, str):
            raise TypeError(
                "provider_event_id must be a string."
            )

        if not provider_event_id.strip():
            raise ValueError(
                "provider_event_id must be a non-empty string."
            )

        key = (
            provider,
            provider_event_id,
        )

        return (
            self._store.has_purchase(
                provider,
                provider_event_id,
            )
            or key in self._staged_purchase_records
        )

    def is_business_active(
        self,
        business_id: str,
    ) -> bool:
        """
        Return whether a business is active in shared committed state or
        this transaction's staged state.
        """
        business_id = self._business_id(
            business_id,
        )

        return (
            business_id in self._store.active_businesses
            or business_id in self._staged_active_businesses
        )

    def is_paid_business(
        self,
        business_id: str,
    ) -> bool:
        """
        Return whether a business is recognized as paid in shared committed
        state or this transaction's staged state.
        """
        business_id = self._business_id(
            business_id,
        )

        return (
            business_id in self._store.paid_businesses
            or business_id in self._staged_paid_businesses
        )
