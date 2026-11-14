from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class MetaWhatsAppIdentityProvisioningVerifier:
    """Independently verify a Meta phone-number/WABA assignment.

    provider_reference is the WhatsApp Business Account ID (WABA ID).
    assigned_identity is the Meta phone-number ID.

    This verifies the Meta-side assignment. The application must still
    authorise the local business owner before activating the identity.
    """

    _PROVIDERS = {"meta", "meta_whatsapp", "whatsapp_meta"}

    def __init__(
        self,
        *,
        access_token: str,
        graph_api_version: str,
        timeout_seconds: float = 10.0,
        max_pages: int = 20,
    ) -> None:
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("access_token must be non-empty.")
        if (
            not isinstance(graph_api_version, str)
            or not graph_api_version.strip()
            or not graph_api_version.startswith("v")
        ):
            raise ValueError("A valid Graph API version is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if max_pages < 1:
            raise ValueError("max_pages must be positive.")

        self._access_token = access_token.strip()
        self._version = graph_api_version.strip()
        self._timeout = float(timeout_seconds)
        self._max_pages = int(max_pages)

    def _get(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "graph.facebook.com"
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Untrusted Meta Graph API URL.")

        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
                "User-Agent": "AminationAI/1.0",
            },
            method="GET",
        )

        with urlopen(request, timeout=self._timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise RuntimeError("Meta Graph API returned an unsuccessful status.")
            payload = json.loads(response.read().decode("utf-8"))

        if not isinstance(payload, dict) or "error" in payload:
            raise RuntimeError("Meta Graph API returned an invalid response.")
        return payload

    def verify_assignment(
        self,
        *,
        business_id: str,
        provider: str,
        assigned_identity: str,
        provider_reference: str,
    ) -> bool:
        if (
            not isinstance(business_id, str)
            or not business_id.strip()
            or provider not in self._PROVIDERS
            or not isinstance(assigned_identity, str)
            or not assigned_identity.isdigit()
            or not isinstance(provider_reference, str)
            or not provider_reference.isdigit()
        ):
            return False

        phone_id = assigned_identity
        waba_id = provider_reference
        base = f"https://graph.facebook.com/{self._version}"

        try:
            # Confirm that Meta recognises this phone-number ID.
            phone = self._get(
                f"{base}/{phone_id}?"
                + urlencode({"fields": "id,display_phone_number,verified_name"})
            )
            if phone.get("id") != phone_id:
                return False

            # Confirm that this phone-number ID belongs to the claimed WABA.
            next_url = (
                f"{base}/{waba_id}/phone_numbers?"
                + urlencode({"fields": "id", "limit": "100"})
            )

            for _ in range(self._max_pages):
                page = self._get(next_url)
                rows = page.get("data")
                if not isinstance(rows, list):
                    return False

                for row in rows:
                    if isinstance(row, dict) and row.get("id") == phone_id:
                        return True

                paging = page.get("paging")
                next_link = (
                    paging.get("next")
                    if isinstance(paging, dict)
                    else None
                )
                if not next_link:
                    return False
                if not isinstance(next_link, str):
                    return False
                next_url = next_link

            # Never accept a result if pagination could not be completed.
            return False

        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            json.JSONDecodeError,
        ):
            return False
