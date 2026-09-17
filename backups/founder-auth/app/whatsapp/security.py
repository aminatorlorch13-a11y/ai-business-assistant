from __future__ import annotations

import hashlib
import hmac


class WhatsAppSignatureError(PermissionError):
    """The inbound provider signature could not be trusted."""


def normalize_sender_id(sender_id: str) -> str:
    """
    Normalize an externally supplied sender identifier.

    The provider-specific adapter may perform stricter normalization before
    this function. This boundary deliberately does not assume that every
    future WhatsApp provider represents senders identically.
    """
    if not isinstance(sender_id, str):
        raise TypeError("sender_id must be a string.")

    normalized = sender_id.strip()

    if not normalized:
        raise ValueError("sender_id must be non-empty.")

    if len(normalized) > 256:
        raise ValueError("sender_id is too long.")

    if any(ord(character) < 32 for character in normalized):
        raise ValueError("sender_id contains control characters.")

    return normalized


def hash_sender_id(sender_id: str, secret: str) -> str:
    """
    Produce a keyed, non-reversible sender identifier for persistence.

    A keyed hash is used so a database-only compromise does not directly
    expose the original WhatsApp sender identifier.
    """
    normalized = normalize_sender_id(sender_id)

    if not isinstance(secret, str) or not secret:
        raise ValueError("sender hash secret must be non-empty.")

    return hmac.new(
        secret.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
) -> None:
    """
    Verify a provider webhook signature.

    Expected format:
        sha256=<lowercase hex digest>

    The comparison is constant-time.
    """
    if not isinstance(raw_body, bytes):
        raise TypeError("raw_body must be bytes.")

    if not isinstance(signature_header, str) or not signature_header.strip():
        raise WhatsAppSignatureError("Missing webhook signature.")

    if not isinstance(secret, str) or not secret:
        raise ValueError("webhook secret must be non-empty.")

    prefix = "sha256="

    if not signature_header.startswith(prefix):
        raise WhatsAppSignatureError("Invalid webhook signature format.")

    supplied = signature_header[len(prefix):]

    if len(supplied) != 64:
        raise WhatsAppSignatureError("Invalid webhook signature length.")

    try:
        int(supplied, 16)
    except ValueError as exc:
        raise WhatsAppSignatureError("Invalid webhook signature encoding.") from exc

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(supplied, expected):
        raise WhatsAppSignatureError("Webhook signature verification failed.")
