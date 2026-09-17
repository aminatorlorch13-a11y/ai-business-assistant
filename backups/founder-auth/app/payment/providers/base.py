from abc import ABC, abstractmethod

from app.payment.event import PaymentProviderEvent


class PaymentProviderAdapter(ABC):
    """
    Provider-specific boundary.

    Implementations translate external provider requests/events
    into PaymentProviderEvent objects.

    Provider-specific authentication, signatures, payload formats,
    HTTP behavior, and credentials belong here rather than in the
    commercial domain.
    """

    @abstractmethod
    def parse_event(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        received_at,
    ) -> PaymentProviderEvent:
        raise NotImplementedError
