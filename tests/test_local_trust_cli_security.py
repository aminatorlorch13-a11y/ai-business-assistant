import os

import pytest

from app.auth import local_trust


def test_local_trust_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LOCAL_TRUST_CLI", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    assert local_trust.is_enabled() is False
    with pytest.raises(PermissionError):
        local_trust.require_enabled()


def test_local_trust_is_rejected_outside_development_or_test(monkeypatch):
    monkeypatch.setenv("LOCAL_TRUST_CLI", "true")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(PermissionError):
        local_trust.require_enabled()


def test_customer_browser_boundary_has_no_local_trust_switch():
    source = open("app/cli/chat.py", encoding="utf-8").read()
    assert "local_trust.require_enabled" not in source
    assert "LOCAL_TRUST_CLI" not in source
