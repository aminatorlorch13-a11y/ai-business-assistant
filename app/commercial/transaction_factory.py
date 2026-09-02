from typing import Protocol, runtime_checkable

from app.commercial.transaction import CommercialTransaction


@runtime_checkable
class CommercialTransactionFactory(Protocol):
    """Boundary for creating commercial transactions.

    Implementations must return a fresh transaction for each operation.
    The caller owns the transaction lifecycle and is responsible for
    committing or rolling it back.
    """

    def begin(self) -> CommercialTransaction:
        """Create and return a new commercial transaction."""
        ...
