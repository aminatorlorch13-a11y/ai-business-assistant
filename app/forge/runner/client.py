"""Authenticated client for the independent Forge Linux runner."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class ForgeRunnerClientError(RuntimeError):
    pass


class ForgeRunnerClient:
    def __init__(self, base_url: str, token: str, timeout: int = 20):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("A valid Forge runner URL is required.")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("A Forge runner token is required.")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            raise ValueError("Runner timeout must be a positive integer.")
        try:
            parsed = urlsplit(base_url.strip())
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Invalid Forge runner URL.") from exc
        if (
            not hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")
        ):
            raise ValueError("Invalid Forge runner URL.")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and hostname.lower() in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Remote Forge runner URLs must use HTTPS.")
        self.base_url = base_url.strip().rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", "Runner request failed")
            except Exception:
                detail = "Runner request failed"
            raise ForgeRunnerClientError(detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ForgeRunnerClientError("The independent Forge runner is unavailable.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ForgeRunnerClientError("The Forge runner returned an invalid response.") from exc
        if not isinstance(result, dict):
            raise ForgeRunnerClientError("The Forge runner returned an invalid response.")
        return result

    def open_session(self, files: dict[str, str]) -> str:
        result = self._request("POST", "/v1/sessions", {"files": files})
        session_id = result.get("session_id")
        try:
            return self._validate_session_id(session_id)
        except ValueError as exc:
            raise ForgeRunnerClientError(
                "The runner did not return a valid session."
            ) from exc

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise ValueError("Invalid Forge runner session identifier.")
        return session_id

    def execute(self, session_id: str, command: str, timeout_seconds: int = 30) -> dict:
        session_id = self._validate_session_id(session_id)
        return self._request(
            "POST",
            f"/v1/sessions/{session_id}/execute",
            {"command": command, "timeout_seconds": timeout_seconds},
        )

    def sync_files(self, session_id: str, files: dict[str, str]) -> None:
        session_id = self._validate_session_id(session_id)
        if not isinstance(files, dict):
            raise ValueError("Runner workspace files must be a dictionary.")
        self._request("PUT", f"/v1/sessions/{session_id}/files", {"files": files})

    def read_files(self, session_id: str) -> dict[str, str]:
        session_id = self._validate_session_id(session_id)
        result = self._request("GET", f"/v1/sessions/{session_id}/files")
        files = result.get("files")
        if not isinstance(files, dict):
            raise ForgeRunnerClientError("The runner returned an invalid file snapshot.")
        return files

    def close_session(self, session_id: str) -> None:
        session_id = self._validate_session_id(session_id)
        self._request("DELETE", f"/v1/sessions/{session_id}")
