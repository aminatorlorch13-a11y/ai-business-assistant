from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.whatsapp.provider import (
    WhatsAppProvider,
    WhatsAppProviderError,
    WhatsAppProviderOutcomeUnknown,
)


class MetaWhatsAppCloudProvider(WhatsAppProvider):
    """Real outbound WhatsApp provider using Meta's Cloud API."""

    API_ROOT = "https://graph.facebook.com"

    def __init__(
        self,
        access_token: str,
        graph_api_version: str,
        timeout: float = 20.0,
    ) -> None:
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("Meta access token is required.")

        if not re.fullmatch(r"v\d+\.\d+", graph_api_version or ""):
            raise ValueError("A valid Meta Graph API version is required.")

        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number.")

        self._access_token = access_token.strip()
        self._api_version = graph_api_version
        self._timeout = float(timeout)

    def send_text(
        self,
        provider_account_id: str,
        recipient: str,
        text: str,
    ) -> str:
        if not isinstance(provider_account_id, str) or not provider_account_id.isdigit():
            raise ValueError("A valid Meta phone number ID is required.")

        if not isinstance(recipient, str):
            raise ValueError("WhatsApp recipient must be a string.")

        recipient = recipient.strip()
        if recipient.startswith("+"):
            recipient = recipient[1:]

        if not recipient.isdigit():
            raise ValueError("Recipient must be an international number using digits.")

        if not isinstance(text, str) or not text.strip():
            raise ValueError("Message text must be non-empty.")

        if len(text) > 4096:
            raise ValueError("WhatsApp text exceeds the 4096-character limit.")

        url = (
            f"{self.API_ROOT}/{self._api_version}/"
            f"{provider_account_id}/messages"
        )

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text,
            },
        }

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._timeout) as response:
                status = response.status
                body = response.read()

        except HTTPError as exc:
            if 500 <= exc.code <= 599:
                raise WhatsAppProviderOutcomeUnknown(
                    "Meta returned a server error; delivery must be reconciled."
                ) from exc

            raise WhatsAppProviderError(
                f"Meta rejected the WhatsApp request (HTTP {exc.code})."
            ) from exc

        except (URLError, TimeoutError, OSError) as exc:
            raise WhatsAppProviderOutcomeUnknown(
                "Meta request outcome is unknown; blind retry is forbidden."
            ) from exc

        if not 200 <= status < 300:
            raise WhatsAppProviderError(
                f"Unexpected Meta HTTP status: {status}."
            )

        try:
            result = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WhatsAppProviderOutcomeUnknown(
                "Meta response could not be verified."
            ) from exc

        if isinstance(result, dict) and result.get("error"):
            raise WhatsAppProviderError(
                "Meta reported that the WhatsApp message was rejected."
            )

        messages = result.get("messages") if isinstance(result, dict) else None

        if not isinstance(messages, list) or not messages:
            raise WhatsAppProviderOutcomeUnknown(
                "Meta response did not contain a confirmed message ID."
            )

        message_id = messages[0].get("id") if isinstance(messages[0], dict) else None

        if not isinstance(message_id, str) or not message_id.strip():
            raise WhatsAppProviderOutcomeUnknown(
                "Meta response contained no valid message ID."
            )

        return message_id
