from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MetaEmbeddedSignupError(RuntimeError):
    """A Meta Embedded Signup operation failed safely."""


@dataclass(frozen=True)
class MetaEmbeddedSignupConfig:
    app_id: str
    app_secret: str
    graph_api_version: str

    def __post_init__(self) -> None:
        if not self.app_id or not self.app_id.isdigit():
            raise ValueError("Meta app ID must contain digits only.")
        if not isinstance(self.app_secret, str) or not self.app_secret:
            raise ValueError("Meta app secret must be configured.")
        if not re.fullmatch(r"v\d+\.\d+", self.graph_api_version):
            raise ValueError("Invalid Meta Graph API version.")

    @classmethod
    def from_environment(cls) -> MetaEmbeddedSignupConfig | None:
        names = (
            "META_APP_ID",
            "META_APP_SECRET",
            "META_GRAPH_API_VERSION",
        )
        values = {name: os.getenv(name) for name in names}

        if not any(values.values()):
            return None

        if not all(values.values()):
            raise ValueError(
                "Meta Embedded Signup configuration is incomplete."
            )

        return cls(
            app_id=values["META_APP_ID"],
            app_secret=values["META_APP_SECRET"],
            graph_api_version=values["META_GRAPH_API_VERSION"],
        )


class MetaGraphClient:
    """Small, real HTTP client for the Meta Graph API."""

    BASE_URL = "https://graph.facebook.com"
    TIMEOUT_SECONDS = 15

    def __init__(self, graph_api_version: str) -> None:
        if not re.fullmatch(r"v\d+\.\d+", graph_api_version):
            raise ValueError("Invalid Meta Graph API version.")
        self._version = graph_api_version

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        access_token: str | None = None,
    ) -> dict:
        if not path.startswith("/") or ".." in path:
            raise ValueError("Invalid Meta Graph API path.")

        url = (
            f"{self.BASE_URL}/{self._version}{path}"
            f"?{urlencode(params or {})}"
        )
        headers = {"Accept": "application/json"}

        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"

        request = Request(
            url,
            data=b"" if method == "POST" else None,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(
                request,
                timeout=self.TIMEOUT_SECONDS,
            ) as response:
                raw = response.read(2 * 1024 * 1024)
        except HTTPError as exc:
            raise MetaEmbeddedSignupError(
                f"Meta Graph API rejected the request (HTTP {exc.code})."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise MetaEmbeddedSignupError(
                "Meta Graph API could not be reached."
            ) from None

        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MetaEmbeddedSignupError(
                "Meta Graph API returned an invalid response."
            ) from None

        if not isinstance(payload, dict):
            raise MetaEmbeddedSignupError(
                "Meta Graph API returned an unexpected response."
            )

        if "error" in payload:
            raise MetaEmbeddedSignupError(
                "Meta Graph API reported an operation error."
            )

        return payload

    def exchange_authorization_code(
        self,
        *,
        app_id: str,
        app_secret: str,
        code: str,
    ) -> str:
        payload = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "code": code,
            },
        )

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise MetaEmbeddedSignupError(
                "Meta did not return an authorization token."
            )

        return token

    def find_phone_number(
        self,
        *,
        waba_id: str,
        phone_number_id: str,
        access_token: str,
    ) -> dict:
        """Prove the selected phone number belongs to the authorized WABA."""
        after: str | None = None

        for _ in range(100):
            params = {
                "fields": "id,display_phone_number,verified_name",
                "limit": "100",
            }
            if after:
                params["after"] = after

            payload = self._request(
                "GET",
                f"/{waba_id}/phone_numbers",
                params=params,
                access_token=access_token,
            )

            rows = payload.get("data")
            if not isinstance(rows, list):
                raise MetaEmbeddedSignupError(
                    "Meta returned an invalid phone-number listing."
                )

            for row in rows:
                if isinstance(row, dict) and row.get("id") == phone_number_id:
                    return row

            paging = payload.get("paging")
            if not isinstance(paging, dict) or not paging.get("next"):
                break

            cursors = paging.get("cursors")
            next_after = (
                cursors.get("after")
                if isinstance(cursors, dict)
                else None
            )
            if not isinstance(next_after, str) or not next_after:
                raise MetaEmbeddedSignupError(
                    "Meta pagination could not be verified."
                )
            after = next_after

        raise MetaEmbeddedSignupError(
            "The selected phone number was not found in the authorized WABA."
        )

    def subscribe_app(
        self,
        *,
        waba_id: str,
        access_token: str,
    ) -> None:
        self._request(
            "POST",
            f"/{waba_id}/subscribed_apps",
            access_token=access_token,
        )


@dataclass(frozen=True)
class MetaEmbeddedSignupResult:
    business_id: str
    waba_id: str
    phone_number_id: str
    display_phone_number: str | None
    verified_name: str | None


class MetaEmbeddedSignupService:
    """
    Completes the server-side portion of Meta Embedded Signup.

    persist_token must encrypt and durably store the tenant-specific token.
    This service never returns or logs the access token.
    """

    def __init__(
        self,
        *,
        config: MetaEmbeddedSignupConfig,
        persist_token: Callable[[str, str, str, str], None],
    ) -> None:
        if not isinstance(config, MetaEmbeddedSignupConfig):
            raise TypeError("config must be MetaEmbeddedSignupConfig.")
        if not callable(persist_token):
            raise TypeError("persist_token must be callable.")

        self._config = config
        self._persist_token = persist_token
        self._graph = MetaGraphClient(config.graph_api_version)

    def complete_signup(
        self,
        *,
        business_id: str,
        authorization_code: str,
        waba_id: str,
        phone_number_id: str,
    ) -> MetaEmbeddedSignupResult:
        for name, value in (
            ("business_id", business_id),
            ("authorization_code", authorization_code),
            ("waba_id", waba_id),
            ("phone_number_id", phone_number_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")

        if len(authorization_code) > 4096:
            raise ValueError("Authorization code is too long.")

        if not waba_id.isdigit() or not phone_number_id.isdigit():
            raise ValueError("Meta asset identifiers must contain digits only.")

        token = self._graph.exchange_authorization_code(
            app_id=self._config.app_id,
            app_secret=self._config.app_secret,
            code=authorization_code,
        )

        phone = self._graph.find_phone_number(
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            access_token=token,
        )

        # Subscribe only after Meta confirms the phone-number/WABA relationship.
        self._graph.subscribe_app(
            waba_id=waba_id,
            access_token=token,
        )

        # The callback must encrypt and persist this token for this tenant.
        # If storage fails, onboarding fails rather than claiming success.
        self._persist_token(
            business_id,
            waba_id,
            phone_number_id,
            token,
        )

        display_number = phone.get("display_phone_number")
        verified_name = phone.get("verified_name")

        return MetaEmbeddedSignupResult(
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            display_phone_number=(
                display_number if isinstance(display_number, str) else None
            ),
            verified_name=(
                verified_name if isinstance(verified_name, str) else None
            ),
        )
