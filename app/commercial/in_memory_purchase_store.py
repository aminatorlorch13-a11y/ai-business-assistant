from app.commercial.purchase_record import PurchaseRecord


class InMemoryPurchaseStore:
    """
    In-memory implementation of the purchase persistence boundary.

    The store uses the provider/event pair as the idempotency identity.

    This implementation is intentionally small and deterministic so the
    commercial application layer can be tested without coupling it to a
    specific database.

    Production persistence must enforce the same uniqueness invariant at
    the database level.
    """

    def __init__(self) -> None:
        self._records: dict[
            tuple[str, str],
            PurchaseRecord,
        ] = {}

    @staticmethod
    def _key(
        provider: str,
        provider_event_id: str,
    ) -> tuple[str, str]:
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

        return provider, provider_event_id

    def get(
        self,
        provider: str,
        provider_event_id: str,
    ) -> PurchaseRecord | None:
        """
        Return the record for a provider event, if it exists.
        """
        key = self._key(
            provider,
            provider_event_id,
        )

        return self._records.get(key)

    def save(
        self,
        record: PurchaseRecord,
    ) -> None:
        """
        Save a purchase record exactly once.

        Duplicate provider/event identities are rejected rather than
        silently replacing historical evidence.
        """
        if not isinstance(record, PurchaseRecord):
            raise TypeError(
                "record must be a PurchaseRecord."
            )

        key = self._key(
            record.provider,
            record.provider_event_id,
        )

        if key in self._records:
            raise ValueError(
                "A purchase record already exists for this provider event."
            )

        self._records[key] = record
