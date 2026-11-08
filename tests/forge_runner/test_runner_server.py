import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app.forge.runner.server as runner


@pytest.fixture
def runner_http(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "TOKEN", "test-runner-token")
    monkeypatch.setattr(runner, "_sessions", {})
    monkeypatch.setattr(runner, "_session_last_used", {})
    monkeypatch.setattr(runner, "_active_sessions", set())

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def request(base, method, path, payload=None, token="test-runner-token"):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        base + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def create_session(base, files=None):
    status, body = request(
        base,
        "POST",
        "/v1/sessions",
        {"files": files or {}},
    )
    assert status == 201, body
    return body["session_id"]


def test_runner_requires_bearer_authentication(runner_http):
    status, body = request(
        runner_http,
        "POST",
        "/v1/sessions",
        {"files": {}},
        token="wrong-token",
    )
    assert status == 401
    assert body["error"] == "Unauthorized"


def test_session_file_upload_and_download_round_trip(runner_http):
    session_id = create_session(runner_http, {"hello.txt": "first"})
    path = f"/v1/sessions/{session_id}/files"

    status, body = request(
        runner_http,
        "PUT",
        path,
        {"files": {"nested/hello.txt": "updated"}},
    )
    assert status == 200
    assert body == {"updated": True, "file_count": 1}

    status, body = request(runner_http, "GET", path)
    assert status == 200
    assert body["files"] == {"nested/hello.txt": "updated"}


def test_active_session_rejects_other_operations_and_expiry(runner_http):
    session_id = create_session(runner_http, {"hello.txt": "safe"})
    directory = runner._sessions[session_id]
    files_path = f"/v1/sessions/{session_id}/files"

    reserved_directory = runner._begin_session_use(session_id)
    assert reserved_directory == directory

    with runner._lock:
        runner._session_last_used[session_id] = (
            time.monotonic() - runner.SESSION_IDLE_TTL_SECONDS - 10
        )

    assert runner._cleanup_expired_sessions(
        time.monotonic() + runner.SESSION_IDLE_TTL_SECONDS + 10
    ) == 0
    assert directory.is_dir()

    status, _ = request(
        runner_http, "GET", files_path
    )
    assert status == 409

    status, _ = request(
        runner_http, "PUT", files_path, {"files": {"new.txt": "blocked"}}
    )
    assert status == 409

    status, _ = request(
        runner_http, "POST",
        f"/v1/sessions/{session_id}/execute",
        {"command": "not-executed"},
    )
    assert status == 429

    status, _ = request(
        runner_http, "DELETE", f"/v1/sessions/{session_id}"
    )
    assert status == 409
    assert directory.is_dir()

    runner._end_session_use(session_id)

    assert runner._cleanup_expired_sessions(
        time.monotonic() + runner.SESSION_IDLE_TTL_SECONDS + 10
    ) == 1
    assert not directory.exists()
    assert session_id not in runner._sessions


def test_different_sessions_can_be_reserved_concurrently(runner_http):
    first = create_session(runner_http)
    second = create_session(runner_http)

    first_path = runner._begin_session_use(first)
    second_path = runner._begin_session_use(second)

    assert first_path.is_dir()
    assert second_path.is_dir()
    assert first != second

    runner._end_session_use(first)
    runner._end_session_use(second)


def test_execute_route_reserves_and_releases_session(runner_http, monkeypatch):
    session_id = create_session(runner_http, {"main.py": "print('safe')"})
    observed = {}

    def fake_execute(directory, command, timeout):
        observed["directory"] = directory
        observed["command"] = command
        observed["timeout"] = timeout
        observed["reserved"] = session_id in runner._active_sessions
        return {
            "exit_code": 0,
            "output": "mocked",
            "timed_out": False,
            "duration_limit_seconds": timeout,
        }

    monkeypatch.setattr(runner, "_execute", fake_execute)

    status, body = request(
        runner_http,
        "POST",
        f"/v1/sessions/{session_id}/execute",
        {"command": "safe-test", "timeout_seconds": 12},
    )

    assert status == 200
    assert body["output"] == "mocked"
    assert observed["command"] == "safe-test"
    assert observed["timeout"] == 12
    assert observed["reserved"] is True
    assert observed["directory"] == runner._sessions[session_id]
    assert session_id not in runner._active_sessions


def test_idle_session_cleanup_removes_workspace(runner_http):
    session_id = create_session(runner_http, {"old.txt": "temporary"})
    directory = runner._sessions[session_id]

    with runner._lock:
        runner._session_last_used[session_id] = (
            time.monotonic() - runner.SESSION_IDLE_TTL_SECONDS - 10
        )

    removed = runner._cleanup_expired_sessions(
        time.monotonic() + runner.SESSION_IDLE_TTL_SECONDS + 10
    )

    assert removed == 1
    assert not directory.exists()
    assert session_id not in runner._sessions
    assert session_id not in runner._session_last_used
