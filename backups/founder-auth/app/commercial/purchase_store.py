from typing import Protocol

from app.commercial.purchase_record import PurchaseRecord


class PurchaseStore(Protocol):
    """
    Persistence boundary for processed purchase records.

    Implementations are responsible for enforcing uniqueness of the
    provider/event identity.

    The commercial application layer must be able to ask whether an event
    was already recorded without knowing which database or persistence
    technology is being used.
    """

    def get(
        self,
        provider: str,
        provider_event_id: str,
    ) -> PurchaseRecord | None:
        """
        Return the existing record for an event, if present.
        """
        ...

    def save(self, record: PurchaseRecord) -> None:
        """
        Persist a purchase record.

        Implementations must reject duplicate
        (provider, provider_event_id) identities.
        """
        ...
