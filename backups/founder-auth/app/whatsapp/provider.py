from __future__ import annotations

from abc import ABC, abstractmethod


class WhatsAppProviderError(RuntimeError):
    """The provider definitely rejected or failed the outbound operation."""


class WhatsAppProviderOutcomeUnknown(RuntimeError):
    """
    The provider outcome cannot safely be determined.

    The caller must never blindly resend an operation that reaches this state.
    """


class WhatsAppProvider(ABC):
    """
    External WhatsApp provider boundary.

    The Assistant Core does not know about this interface.
    Provider-specific delivery behavior remains isolated here.
    """

    @abstractmethod
    def send_text(
        self,
        provider_account_id: str,
        recipient: str,
        text: str,
    ) -> str:
        """
        Send a real text message.

        Returns a provider message ID only after confirmed success.

        Raises:
            WhatsAppProviderError:
                The provider definitely rejected/failed the operation.

            WhatsAppProviderOutcomeUnknown:
                The application cannot safely determine whether the
                provider accepted the operation.
        """
        raise NotImplementedError
