from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


CONNECTOR_SCOPES: dict[str, frozenset[str]] = {
    "whatsapp_business": frozenset({
        "messages.read", "messages.send", "profile.read",
    }),
    "gmail": frozenset({"email.read", "email.send"}),
    "google_calendar": frozenset({
        "calendar.events.read", "calendar.events.write",
    }),
    "facebook_pages": frozenset({"pages.read", "pages.publish"}),
    "telegram": frozenset({"messages.read", "messages.send"}),
    "google_drive": frozenset({"files.read", "files.write"}),
    "github": frozenset({"repos.read", "repos.write"}),
}


@dataclass(frozen=True)
class IntegrationConnection:
    connection_id: str
    business_id: str
    user_id: str
    provider: str
    external_account_id: str
    status: str
    created_at: datetime
    revoked_at: datetime | None
