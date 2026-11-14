from __future__ import annotations

from app.whatsapp.security import verify_webhook_signature
from app.whatsapp.service import (
    WhatsAppChannelService,
    WhatsAppInboundEnvelope,
)


def handle_whatsapp(
    *,
    service: WhatsAppChannelService,
    raw_body: bytes,
    signature_header: str,
    webhook_secret: str,
    envelope: WhatsAppInboundEnvelope,
) -> str:
    """
    Verify the original provider webhook and pass the validated
    inbound envelope to the durable WhatsApp channel service.

    No in-memory assistant, tenant inference, or simulated delivery.
    """
    if not isinstance(service, WhatsAppChannelService):
        raise TypeError("service must be a WhatsAppChannelService.")

    if not isinstance(envelope, WhatsAppInboundEnvelope):
        raise TypeError("envelope must be a WhatsAppInboundEnvelope.")

    verify_webhook_signature(
        raw_body=raw_body,
        signature_header=signature_header,
        secret=webhook_secret,
    )

    return service.process(envelope)
