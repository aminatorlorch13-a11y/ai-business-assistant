from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.integrations import google_gmail
from app.integrations.google_gmail import GmailApiClient, GmailApiError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode("utf-8")


def test_list_messages_calls_real_gmail_endpoint_with_search_and_pagination(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse({
            "messages": [{"id": "message_1", "threadId": "thread_1"}],
            "nextPageToken": "next-page",
            "resultSizeEstimate": 42,
        })

    monkeypatch.setattr(google_gmail.urllib.request, "urlopen", fake_urlopen)

    result = GmailApiClient().list_messages(
        access_token="secret-access-token",
        query="from:person@example.com is:unread",
        page_token="previous-page",
        max_results=10,
    )

    assert captured["url"].startswith(google_gmail.GMAIL_API_ROOT + "/messages?")
    params = parse_qs(urlsplit(captured["url"]).query)
    assert params["q"] == ["from:person@example.com is:unread"]
    assert params["pageToken"] == ["previous-page"]
    assert params["maxResults"] == ["10"]
    assert captured["authorization"] == "Bearer secret-access-token"
    assert captured["timeout"] == 20
    assert result == {
        "messages": [{"id": "message_1", "thread_id": "thread_1"}],
        "next_page_token": "next-page",
        "result_size_estimate": 42,
    }


def test_get_message_decodes_headers_and_plain_text_body(monkeypatch):
    encoded = base64.urlsafe_b64encode(b"Hello from Gmail").decode().rstrip("=")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse({
            "id": "message_1",
            "threadId": "thread_1",
            "labelIds": ["INBOX", "UNREAD"],
            "snippet": "Hello from Gmail",
            "internalDate": "1790000000000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "A real message"},
                    {"name": "Date", "value": "Mon, 1 Nov 2026 10:00:00 +0000"},
                ],
                "mimeType": "text/plain",
                "body": {"data": encoded},
            },
        })

    monkeypatch.setattr(google_gmail.urllib.request, "urlopen", fake_urlopen)

    result = GmailApiClient().get_message(
        access_token="secret-access-token",
        message_id="message_1",
    )

    assert captured["url"] == google_gmail.GMAIL_API_ROOT + "/messages/message_1"
    assert result["headers"]["from"] == "sender@example.com"
    assert result["headers"]["subject"] == "A real message"
    assert result["body_text"] == "Hello from Gmail"
    assert result["label_ids"] == ["INBOX", "UNREAD"]


@pytest.mark.parametrize("max_results", [0, 101, True, "25"])
def test_list_messages_rejects_invalid_page_size(max_results):
    with pytest.raises(ValueError):
        GmailApiClient().list_messages(
            access_token="token",
            max_results=max_results,
        )


def test_message_detail_rejects_path_injection():
    with pytest.raises(ValueError):
        GmailApiClient().get_message(
            access_token="token",
            message_id="../other-resource",
        )


def test_list_messages_rejects_malformed_provider_response(monkeypatch):
    monkeypatch.setattr(
        google_gmail.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse({"messages": "not-a-list"}),
    )
    with pytest.raises(GmailApiError):
        GmailApiClient().list_messages(access_token="token")


def test_message_detail_rejects_unexpected_message_id(monkeypatch):
    monkeypatch.setattr(
        google_gmail.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse({"id": "different_message"}),
    )
    with pytest.raises(GmailApiError):
        GmailApiClient().get_message(
            access_token="token",
            message_id="expected_message",
        )
