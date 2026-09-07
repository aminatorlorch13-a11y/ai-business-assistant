from datetime import datetime

from app.commercial.purchase import VerifiedPurchase
from app.payment.event import PaymentProviderEvent
from app.payment.fact_extractor import PaymentFactExtractor
from app.payment.facts import PaymentFacts
from app.payment.request import PaymentVerificationRequest
from app.payment.verification import (
    PaymentVerificationResult,
    PaymentVerificationStatus,
)
from app.payment.verifier import PaymentVerifier


class SemanticPaymentVerifier(PaymentVerifier):
    """
    Stateless semantic payment verifier.

    Converts provider-neutral payment facts into a trusted
    VerifiedPurchase.

    It does not:
    - authenticate provider signatures,
    - activate businesses,
    - process commercial transactions,
    - determine pricing,
    - detect duplicates,
    - or perform external side effects.
    """

    def __init__(
        self,
        extractor: PaymentFactExtractor,
    ) -> None:
        if not isinstance(extractor, PaymentFactExtractor):
            raise TypeError(
                "extractor must be a PaymentFactExtractor."
            )

        self._extractor = extractor

    def verify(
        self,
        event: PaymentProviderEvent,
        request: PaymentVerificationRequest,
    ) -> PaymentVerificationResult:
        if not isinstance(event, PaymentProviderEvent):
            raise TypeError(
                "event must be a PaymentProviderEvent."
            )

        if not isinstance(
            request,
            PaymentVerificationRequest,
        ):
            raise TypeError(
                "request must be a PaymentVerificationRequest."
            )

        facts = self._extractor.extract(event)

        if not isinstance(facts, PaymentFacts):
            raise TypeError(
                "fact extractor must return PaymentFacts."
            )

        if facts.business_id != request.business_id:
            return self._reject(
                "business identity mismatch"
            )

        if facts.payment_status != "paid":
            return self._reject(
                "payment is not confirmed as paid"
            )

        if facts.amount != request.expected_amount:
            return self._reject(
                "payment amount mismatch"
            )

        if facts.currency != request.expected_currency:
            return self._reject(
                "payment currency mismatch"
            )

        if not isinstance(facts.paid_at, datetime):
            return self._reject(
                "payment timestamp is invalid"
            )

        if facts.paid_at.tzinfo is None:
            return self._reject(
                "payment timestamp is not timezone-aware"
            )

        if facts.paid_at.utcoffset() is None:
            return self._reject(
                "payment timestamp is invalid"
            )

        if facts.paid_at > event.received_at:
            return self._reject(
                "payment timestamp occurs after event receipt"
            )

        purchase = VerifiedPurchase(
            provider=event.provider,
            provider_event_id=event.event_id,
            business_id=facts.business_id,
            amount=facts.amount,
            currency=facts.currency,
            paid_at=facts.paid_at,
        )

        return PaymentVerificationResult(
            status=PaymentVerificationStatus.VERIFIED,
            purchase=purchase,
        )

    @staticmethod
    def _reject(
        reason: str,
    ) -> PaymentVerificationResult:
        return PaymentVerificationResult(
            status=PaymentVerificationStatus.REJECTED,
            reason=reason,
        )
