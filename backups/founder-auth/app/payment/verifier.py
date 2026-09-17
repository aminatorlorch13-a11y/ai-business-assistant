from abc import ABC, abstractmethod

from app.payment.event import PaymentProviderEvent
from app.payment.request import PaymentVerificationRequest
from app.payment.verification import PaymentVerificationResult


class PaymentVerifier(ABC):
    """
    Explicit boundary responsible for converting provider events into
    payment-verification outcomes.

    The verification request contains the trusted application-side
    expectation against which the provider event is evaluated.

    Implementations must not:
    - activate businesses,
    - modify commercial state,
    - determine launch-program capacity,
    - process purchases,
    - store credentials,
    - or perform commercial side effects.

    Provider-specific authentication belongs to the provider adapter.

    Implementations must return PaymentVerificationResult.
    """

    @abstractmethod
    def verify(
        self,
        event: PaymentProviderEvent,
        request: PaymentVerificationRequest,
    ) -> PaymentVerificationResult:
        raise NotImplementedError
