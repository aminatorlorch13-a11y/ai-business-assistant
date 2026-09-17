from __future__ import annotations

from urllib.parse import urlparse

from flask import Request


class WebSecurityError(PermissionError):
    """A browser request failed a web security boundary."""


def require_same_origin(request: Request) -> None:
    """Reject cross-origin state-changing browser requests."""
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    candidate = origin or referer
    if not candidate:
        return

    parsed = urlparse(candidate)
    expected = request.host_url.rstrip("/")
    actual = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if actual != expected:
        raise WebSecurityError("Cross-origin request rejected.")
