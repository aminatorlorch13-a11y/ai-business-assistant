from __future__ import annotations

import hashlib


def hash_session_id(session_id: str) -> str:
    """
    Return the canonical storage hash for an opaque authenticated session ID.

    Raw session IDs must never be persisted. This helper is intentionally
    shared by authentication and other security-sensitive session bindings.
    """
    if not isinstance(session_id, str):
        raise TypeError("session_id must be a string.")

    if not session_id.strip():
        raise ValueError("session_id must be a non-empty string.")

    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()
