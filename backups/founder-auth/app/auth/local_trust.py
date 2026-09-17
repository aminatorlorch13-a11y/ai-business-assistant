from __future__ import annotations

import os



class LocalTrustDisabled(PermissionError):
    """The development-only local CLI trust path is disabled."""


def is_enabled() -> bool:
    return os.getenv("LOCAL_TRUST_CLI", "").strip().lower() == "true"


def require_enabled() -> None:
    if not is_enabled():
        raise LocalTrustDisabled("LOCAL_TRUST_CLI is not enabled.")
    if os.getenv("APP_ENV", "development").strip().lower() not in {"development", "test"}:
        raise LocalTrustDisabled("LOCAL_TRUST_CLI is development/test only.")
