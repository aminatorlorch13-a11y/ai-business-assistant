from typing import Protocol, runtime_checkable

from app.commercial.purchase_record import PurchaseRecord


@runtime_checkable
class CommercialTransaction(Protocol):
    """
    Transaction boundary for one atomic commercial operation.

    Implementations must ensure that all operations performed through
    the transaction either become durable together or are rolled back
    together.

    The transaction boundary is deliberately independent of a specific
    database technology.
    """

    def record_purchase_once(
        self,
        record: PurchaseRecord,
    ) -> bool:
        """
        Record a purchase exactly once.

        Return True when this event was newly accepted.

        Return False when the provider/event identity has already been
        processed.

        Duplicate detection must be atomic with persistence.
        """
        ...

    def activate_business(
        self,
        business_id: str,
    ) -> None:
        """
        Activate the specified business inside this transaction.
        """
        ...

    def record_paid_business(
        self,
        business_id: str,
    ) -> None:
        """
        Apply one newly processed paying business to the launch program.
        """
        ...

    def commit(self) -> None:
        """
        Commit the complete commercial transaction.
        """
        ...

    def rollback(self) -> None:
        """
        Roll back all changes made by this transaction.
        """
        ...
