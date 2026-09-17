from dataclasses import dataclass
from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.commercial.transaction_factory import CommercialTransactionFactory

@dataclass(frozen=True)
class PurchaseApplicationResult:
    """
    Immutable result of processing one verified purchase.

    This describes what the application service did. It is not itself
    authorization, payment verification, or persistence state.
    """

    business_id: str
    provider: str
    provider_event_id: str
    processed: bool
    duplicate: bool

    def __post_init__(self) -> None:
        for field_name, value in {
            "business_id": self.business_id,
            "provider": self.provider,
            "provider_event_id": self.provider_event_id,
        }.items():
            if not isinstance(value, str):
                raise TypeError(
                    f"{field_name} must be a string."
                )

            if not value.strip():
                raise ValueError(
                    f"{field_name} must be a non-empty string."
                )

        if not isinstance(self.processed, bool):
            raise TypeError(
                "processed must be a boolean."
            )

        if not isinstance(self.duplicate, bool):
            raise TypeError(
                "duplicate must be a boolean."
            )

        if self.processed == self.duplicate:
            raise ValueError(
                "processed and duplicate must represent distinct outcomes."
            )


class CommercialPurchaseService:
    """Apply one verified purchase through one atomic commercial transaction.

    Payment verification occurs before this service.

    This service:
    - records the verified purchase exactly once,
    - activates the business,
    - records the business as paid for launch accounting,
    - commits all effects atomically,
    - rolls back staged work when a pre-commit operation fails,
    - and produces no commercial side effects for duplicate provider events.

    Commit atomicity belongs to the transaction implementation itself.

    This service does not:
    - verify external payment credentials,
    - determine pricing,
    - authorize capabilities,
    - store payment credentials,
    - classify AI requests,
    - mutate a payment provider,
    - or expose dashboard presentation logic.
    """

    def __init__(
        self,
        transaction_factory: CommercialTransactionFactory,
    ) -> None:
        if not isinstance(
            transaction_factory,
            CommercialTransactionFactory,
        ):
            raise TypeError(
                "transaction_factory must implement "
                "CommercialTransactionFactory."
            )

        self._transaction_factory = transaction_factory

    def process(
        self,
        purchase: VerifiedPurchase,
        recorded_at,
    ) -> PurchaseApplicationResult:
        """Apply one verified purchase exactly once."""

        if not isinstance(purchase, VerifiedPurchase):
            raise TypeError(
                "purchase must be a VerifiedPurchase."
            )

        record = PurchaseRecord(
            purchase=purchase,
            recorded_at=recorded_at,
        )

        transaction = self._transaction_factory.begin()

        try:
            accepted = transaction.record_purchase_once(record)

            if not accepted:
                transaction.rollback()

                return PurchaseApplicationResult(
                    business_id=purchase.business_id,
                    provider=purchase.provider,
                    provider_event_id=purchase.provider_event_id,
                    processed=False,
                    duplicate=True,
                )

            transaction.activate_business(
                purchase.business_id,
            )

            transaction.record_paid_business(
                purchase.business_id,
            )

        except Exception:
            # Only pre-commit failures are rolled back here.
            # If commit itself fails, the transaction owns its own
            # atomic failure/rollback semantics.
            transaction.rollback()
            raise

        transaction.commit()

        return PurchaseApplicationResult(
            business_id=purchase.business_id,
            provider=purchase.provider,
            provider_event_id=purchase.provider_event_id,
            processed=True,
            duplicate=False,
        )
