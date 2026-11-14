from __future__ import annotations

import json


GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GoogleProtocolError(RuntimeError):
    """Invalid or oversized response from a Google endpoint."""


def read_google_json_response(response) -> dict:
    raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise GoogleProtocolError("Google returned an oversized response.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleProtocolError("Google returned an invalid response.") from exc
    if not isinstance(value, dict):
        raise GoogleProtocolError("Google returned an invalid response.")
    return value
