class PaymentVerificationError(Exception):
    """Base error for payment-verification failures."""


class PaymentProviderError(PaymentVerificationError):
    """The payment provider could not be contacted or processed."""


class InvalidPaymentEvent(PaymentVerificationError):
    """The received payment event is malformed or invalid."""


class PaymentAuthenticationError(PaymentVerificationError):
    """Provider authenticity/signature verification failed."""


class UnsupportedPaymentEvent(PaymentVerificationError):
    """The provider event type is not supported."""
