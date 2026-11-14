from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request

from channels.whatsapp_adapter import handle_whatsapp
from app.whatsapp.config import MetaWhatsAppConfig
from app.whatsapp.service import (
    WhatsAppChannelService,
    WhatsAppInboundEnvelope,
)
from app.whatsapp.security import verify_webhook_signature


META_WHATSAPP_PROVIDER = "meta"


def create_meta_whatsapp_blueprint(
    *,
    service: WhatsAppChannelService,
    config: MetaWhatsAppConfig,
) -> Blueprint:
    if not isinstance(service, WhatsAppChannelService):
        raise TypeError("service must be a WhatsAppChannelService.")
    if not isinstance(config, MetaWhatsAppConfig):
        raise TypeError("config must be a MetaWhatsAppConfig.")

    blueprint = Blueprint("meta_whatsapp_webhook", __name__)

    @blueprint.get("/webhooks/whatsapp")
    def verify_webhook():
        mode = request.args.get("hub.mode", "")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")

        if (
            mode != "subscribe"
            or not hmac.compare_digest(
                token.encode("utf-8"),
                config.webhook_verify_token.encode("utf-8"),
            )
            or not challenge
        ):
            return jsonify(error="Webhook verification rejected."), 403

        return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @blueprint.post("/webhooks/whatsapp")
    def receive_webhook():
        raw_body = request.get_data(cache=True, as_text=False)
        signature = request.headers.get("X-Hub-Signature-256", "")

        try:
            verify_webhook_signature(
                raw_body=raw_body,
                signature_header=signature,
                secret=config.webhook_app_secret,
            )
        except (TypeError, ValueError):
            return jsonify(error="Invalid webhook signature."), 401

        try:
            payload = request.get_json(silent=False)
        except Exception:
            return jsonify(error="Invalid JSON payload."), 400

        if not isinstance(payload, dict):
            return jsonify(error="Invalid webhook payload."), 400

        processed = 0

        try:
            for entry in payload.get("entry", []):
                if not isinstance(entry, dict):
                    continue

                for change in entry.get("changes", []):
                    if not isinstance(change, dict):
                        continue

                    value = change.get("value", {})
                    if not isinstance(value, dict):
                        continue

                    metadata = value.get("metadata", {})
                    if not isinstance(metadata, dict):
                        continue

                    account_id = metadata.get("phone_number_id")
                    if not isinstance(account_id, str) or not account_id.isdigit():
                        continue

                    for message in value.get("messages", []):
                        if not isinstance(message, dict):
                            continue

                        # This endpoint deliberately accepts text messages only.
                        if message.get("type") != "text":
                            continue

                        text_data = message.get("text", {})
                        if not isinstance(text_data, dict):
                            continue

                        message_text = text_data.get("body")
                        sender_id = message.get("from")
                        message_id = message.get("id")

                        if not all(
                            isinstance(item, str) and item.strip()
                            for item in (message_text, sender_id, message_id)
                        ):
                            continue

                        verification_service = current_app.extensions.get(
                            "assistant_communication"
                        )
                        if (
                            verification_service is not None
                            and verification_service.handle_whatsapp_verification_message(
                                provider_account_id=account_id,
                                sender_id=sender_id,
                                provider_message_id=message_id,
                                text=message_text,
                            )
                        ):
                            processed += 1
                            continue

                        envelope = WhatsAppInboundEnvelope(
                            provider=META_WHATSAPP_PROVIDER,
                            provider_account_id=account_id,
                            provider_message_id=message_id,
                            sender_id=sender_id,
                            text=message_text,
                        )

                        handle_whatsapp(
                            service=service,
                            raw_body=raw_body,
                            signature_header=signature,
                            webhook_secret=config.webhook_app_secret,
                            envelope=envelope,
                        )
                        processed += 1

        except PermissionError:
            return jsonify(error="WhatsApp identity or access rejected."), 403
        except (TypeError, ValueError):
            return jsonify(error="Invalid WhatsApp message."), 400
        except Exception:
            # Meta may retry. The durable service must resolve duplicate
            # message IDs and uncertain delivery before another send.
            return jsonify(error="Message processing temporarily failed."), 503

        return jsonify(status="accepted", processed=processed), 200

    return blueprint
