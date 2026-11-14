from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request


GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = 1024 * 1024


class GmailApiError(RuntimeError):
    """Safe Gmail API failure without credentials or provider response leakage."""


def _read_json(response) -> dict:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise GmailApiError("Gmail returned an oversized response.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GmailApiError("Gmail returned an invalid response.") from exc
    if not isinstance(value, dict):
        raise GmailApiError("Gmail returned an invalid response.")
    return value


def _request_json(url: str, access_token: str) -> dict:
    if not isinstance(access_token, str) or not access_token:
        raise GmailApiError("Gmail access is unavailable.")

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + access_token,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return _read_json(response)
    except urllib.error.HTTPError as exc:
        # Do not expose Google's response body or request credentials.
        if exc.code == 401:
            raise GmailApiError("Google rejected the Gmail access token.") from exc
        if exc.code == 403:
            raise GmailApiError("Google denied Gmail read access.") from exc
        if exc.code == 404:
            raise GmailApiError("The requested Gmail message was not found.") from exc
        if exc.code == 429:
            raise GmailApiError("Google Gmail rate limit reached. Try again shortly.") from exc
        raise GmailApiError("Google Gmail request failed.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GmailApiError("Google Gmail is temporarily unreachable.") from exc


def _decode_body(data: str) -> str:
    if not isinstance(data, str) or not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        if len(raw) > MAX_BODY_BYTES:
            raise GmailApiError("Gmail message body exceeds the allowed size.")
        return raw.decode("utf-8", errors="replace")
    except (ValueError, base64.binascii.Error) as exc:
        raise GmailApiError("Gmail returned an invalid message body.") from exc


def _collect_plain_text(part: dict, output: list[str]) -> None:
    if not isinstance(part, dict):
        return
    mime_type = part.get("mimeType")
    body = part.get("body")
    if (
        mime_type == "text/plain"
        and isinstance(body, dict)
        and isinstance(body.get("data"), str)
    ):
        output.append(_decode_body(body["data"]))
    children = part.get("parts", [])
    if isinstance(children, list):
        for child in children:
            _collect_plain_text(child, output)


def _headers(payload: dict) -> dict[str, str]:
    result = {}
    headers = payload.get("headers", [])
    if not isinstance(headers, list):
        return result
    allowed = {"from", "to", "subject", "date"}
    for item in headers:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and name.lower() in allowed and isinstance(value, str):
            result[name.lower()] = value[:2000]
    return result


class GmailApiClient:
    """Read-only Gmail API client. It has no send, modify, or delete methods."""

    def list_messages(
        self, *, access_token: str, query: str = "",
        page_token: str | None = None, max_results: int = 25,
    ) -> dict:
        if not isinstance(query, str) or len(query) > 500:
            raise ValueError("Gmail search query is invalid.")
        if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100.")
        if page_token is not None and (
            not isinstance(page_token, str) or not page_token or len(page_token) > 4096
        ):
            raise ValueError("Gmail page token is invalid.")

        params = {"maxResults": str(max_results)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        url = GMAIL_API_ROOT + "/messages?" + urllib.parse.urlencode(params)
        payload = _request_json(url, access_token)

        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise GmailApiError("Gmail returned an invalid message list.")

        normalized = []
        for item in messages:
            if not isinstance(item, dict):
                raise GmailApiError("Gmail returned an invalid message reference.")
            message_id = item.get("id")
            thread_id = item.get("threadId")
            if not isinstance(message_id, str) or not message_id or len(message_id) > 256:
                raise GmailApiError("Gmail returned an invalid message reference.")
            normalized.append({
                "id": message_id,
                "thread_id": thread_id if isinstance(thread_id, str) else None,
            })

        next_token = payload.get("nextPageToken")
        if next_token is not None and (
            not isinstance(next_token, str) or len(next_token) > 4096
        ):
            raise GmailApiError("Gmail returned an invalid page token.")

        estimate = payload.get("resultSizeEstimate", 0)
        if not isinstance(estimate, int) or isinstance(estimate, bool) or estimate < 0:
            estimate = 0

        return {
            "messages": normalized,
            "next_page_token": next_token,
            "result_size_estimate": estimate,
        }

    def get_message(self, *, access_token: str, message_id: str) -> dict:
        if (
            not isinstance(message_id, str)
            or not message_id
            or len(message_id) > 256
            or not re.fullmatch(r"[A-Za-z0-9_-]+", message_id)
        ):
            raise ValueError("Gmail message ID is invalid.")

        url = GMAIL_API_ROOT + "/messages/" + urllib.parse.quote(message_id, safe="")
        payload = _request_json(url, access_token)

        returned_id = payload.get("id")
        if returned_id != message_id:
            raise GmailApiError("Gmail returned an unexpected message.")

        headers = _headers(payload.get("payload", {}))
        body_parts = []
        _collect_plain_text(payload.get("payload", {}), body_parts)
        body = "\n".join(part for part in body_parts if part)

        snippet = payload.get("snippet", "")
        if not isinstance(snippet, str):
            snippet = ""

        internal_date = payload.get("internalDate")
        if not isinstance(internal_date, str) or not internal_date.isdigit():
            internal_date = None

        return {
            "id": message_id,
            "thread_id": payload.get("threadId") if isinstance(payload.get("threadId"), str) else None,
            "label_ids": [
                item for item in payload.get("labelIds", [])
                if isinstance(item, str)
            ] if isinstance(payload.get("labelIds", []), list) else [],
            "snippet": snippet[:2000],
            "headers": headers,
            "body_text": body,
            "internal_date": internal_date,
        }
