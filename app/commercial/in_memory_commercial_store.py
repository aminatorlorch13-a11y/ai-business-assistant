from app.commercial.purchase_record import PurchaseRecord


class InMemoryCommercialStore:
    """
    Shared in-memory persistence for commercial transaction state.

    This class represents durable state from the perspective of the
    in-memory transaction implementation.

    Transactions may stage changes privately, but committed state lives
    here and can therefore be observed by later transactions.

    Production persistence must enforce equivalent invariants using a
    real database transaction and database-level uniqueness constraints.
    """

    def __init__(self) -> None:
        self.purchase_records: dict[
            tuple[str, str],
            PurchaseRecord,
        ] = {}
        self.active_businesses: set[str] = set()
        self.paid_businesses: set[str] = set()

    def has_purchase(
        self,
        provider: str,
        provider_event_id: str,
    ) -> bool:
        if not isinstance(provider, str):
            raise TypeError("provider must be a string.")

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

        return (
            provider,
            provider_event_id,
        ) in self.purchase_records

    def add_purchase(
        self,
        record: PurchaseRecord,
    ) -> None:
        if not isinstance(record, PurchaseRecord):
            raise TypeError(
                "record must be a PurchaseRecord."
            )

        key = (
            record.provider,
            record.provider_event_id,
        )

        if key in self.purchase_records:
            raise ValueError(
                "A purchase record already exists for this provider event."
            )

        self.purchase_records[key] = record

    def activate_business(
        self,
        business_id: str,
    ) -> None:
        if not isinstance(business_id, str):
            raise TypeError(
                "business_id must be a string."
            )

        if not business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        self.active_businesses.add(
            business_id,
        )

    def record_paid_business(
        self,
        business_id: str,
    ) -> None:
        if not isinstance(business_id, str):
            raise TypeError(
                "business_id must be a string."
            )

        if not business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        self.paid_businesses.add(
            business_id,
        )
