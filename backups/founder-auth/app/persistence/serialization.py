from __future__ import annotations

from datetime import datetime, timezone


def datetime_to_storage(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("value must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


def datetime_from_storage(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("stored datetime must be a non-empty string.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored datetime must be timezone-aware.")
    return parsed
