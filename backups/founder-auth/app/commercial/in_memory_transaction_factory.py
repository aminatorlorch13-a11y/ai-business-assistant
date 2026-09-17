from app.commercial.in_memory_commercial_store import InMemoryCommercialStore
from app.commercial.in_memory_transaction import InMemoryCommercialTransaction


class InMemoryCommercialTransactionFactory:
    """Create fresh transactions backed by one shared commercial store."""

    def __init__(self, store: InMemoryCommercialStore) -> None:
        if not isinstance(store, InMemoryCommercialStore):
            raise TypeError(
                "store must be an InMemoryCommercialStore."
            )

        self._store = store

    def begin(self) -> InMemoryCommercialTransaction:
        """Return a fresh transaction over the shared store."""
        return InMemoryCommercialTransaction(self._store)
