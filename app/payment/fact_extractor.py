from abc import ABC, abstractmethod

from app.payment.event import PaymentProviderEvent
from app.payment.facts import PaymentFacts


class PaymentFactExtractor(ABC):
    """
    Provider-specific semantic translation boundary.

    Implementations translate an already-received provider event into
    provider-neutral PaymentFacts.

    This layer does not grant trust.
    """

    @abstractmethod
    def extract(
        self,
        event: PaymentProviderEvent,
    ) -> PaymentFacts:
        raise NotImplementedError
