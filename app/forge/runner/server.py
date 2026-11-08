"""Isolated Linux execution service for Amination Forge.

This service must run on a dedicated Linux host with Docker installed.
Generated commands execute only inside disposable, resource-limited containers.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.forge.python_executor import ForgePythonCandidateExecutor

MAX_BODY = 3 * 1024 * 1024
MAX_OUTPUT = 128 * 1024
MAX_FILES = 64
MAX_COMMAND = 4096
SESSION_RE = re.compile(r"^[0-9a-f]{32}$")

ROOT = Path(os.getenv("FORGE_RUNNER_ROOT", "/var/lib/amination-forge")).resolve()
IMAGE = os.getenv("FORGE_RUNNER_IMAGE", "amination-forge-runner:latest")
TOKEN = os.getenv("FORGE_RUNNER_TOKEN", "")
MAX_MEMORY = os.getenv("FORGE_RUNNER_MEMORY", "1g")
MAX_CPUS = os.getenv("FORGE_RUNNER_CPUS", "2")
MAX_PIDS = os.getenv("FORGE_RUNNER_PIDS", "128")
MAX_TIMEOUT = int(os.getenv("FORGE_RUNNER_MAX_TIMEOUT", "120"))
MAX_CONCURRENT_EXECUTIONS = max(1, int(os.getenv("FORGE_RUNNER_MAX_CONCURRENT", "2")))
SESSION_IDLE_TTL_SECONDS = max(60, int(os.getenv("FORGE_RUNNER_SESSION_TTL", "1800")))
SESSION_CLEANUP_INTERVAL_SECONDS = 60

# The runner root is created by main(), not during module import.
_lock = threading.RLock()
_sessions: dict[str, Path] = {}
_session_last_used: dict[str, float] = {}
_active_sessions: set[str] = set()
_execution_slots = threading.BoundedSemaphore(MAX_CONCURRENT_EXECUTIONS)


class RunnerError(Exception):
    pass


class RunnerBusyError(RunnerError):
    pass


def _safe_files(files: object) -> dict[str, str]:
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise RunnerError("Invalid workspace file collection.")
    # An empty runner workspace is valid. Candidate validation intentionally
    # requires at least one file, so delegate only non-empty collections.
    if not files:
        return {}
    try:
        validated = ForgePythonCandidateExecutor._validate_files(files)
    except Exception as exc:
        raise RunnerError("Workspace file validation failed.") from exc
    return validated


def _write_files(directory: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        target = directory.joinpath(*Path(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o777)
        target.write_text(content, encoding="utf-8")
        target.chmod(0o666)
    directory.chmod(0o777)


def _replace_files(directory: Path, files: dict[str, str]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise RunnerError("Invalid runner workspace.")
    for child in directory.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            raise RunnerError("Unsupported workspace entry.")
    _write_files(directory, files)


def _read_files(directory: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RunnerError("Symbolic links are not permitted.")
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        try:
            result[relative] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RunnerError(f"Cannot export workspace file: {relative}") from exc
    return _safe_files(result)


def _workspace(session_id: str) -> Path:
    if not SESSION_RE.fullmatch(session_id):
        raise RunnerError("Invalid runner session identifier.")
    with _lock:
        path = _sessions.get(session_id)
        if path is None or not path.is_dir():
            raise RunnerError("Runner session not found.")
        _session_last_used[session_id] = time.monotonic()
    return path


def _begin_session_use(session_id: str) -> Path:
    """Reserve a session for one operation and protect it from expiry."""
    if not SESSION_RE.fullmatch(session_id):
        raise RunnerError("Invalid runner session identifier.")
    with _lock:
        path = _sessions.get(session_id)
        if path is None or not path.is_dir():
            raise RunnerError("Runner session not found.")
        if session_id in _active_sessions:
            raise RunnerBusyError("Another operation is already using this session.")
        _active_sessions.add(session_id)
        _session_last_used[session_id] = time.monotonic()
        return path


def _end_session_use(session_id: str) -> None:
    """Release a session after execution or file access."""
    with _lock:
        _active_sessions.discard(session_id)
        if session_id in _sessions:
            _session_last_used[session_id] = time.monotonic()


def _cleanup_expired_sessions(now: float | None = None) -> int:
    """Remove idle workspaces but never remove one in active use."""
    current = time.monotonic() if now is None else now
    expired = []
    with _lock:
        for session_id, last_used in list(_session_last_used.items()):
            if session_id in _active_sessions:
                continue
            if current - last_used < SESSION_IDLE_TTL_SECONDS:
                continue
            directory = _sessions.pop(session_id, None)
            _session_last_used.pop(session_id, None)
            if directory is not None:
                expired.append(directory)

    for directory in expired:
        shutil.rmtree(directory, ignore_errors=True)
    return len(expired)


def _session_cleanup_loop() -> None:
    while True:
        time.sleep(SESSION_CLEANUP_INTERVAL_SECONDS)
        try:
            _cleanup_expired_sessions()
        except Exception as exc:
            print(f"[forge-runner] session cleanup failed: {type(exc).__name__}")


def _execute(directory: Path, command: str, timeout: int) -> dict:
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND:
        raise RunnerError("A non-empty command of at most 4096 characters is required.")
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise RunnerError("Invalid command timeout.")
    timeout = max(1, min(timeout, MAX_TIMEOUT))

    if not _execution_slots.acquire(blocking=False):
        raise RunnerBusyError("The Forge runner is busy. Try again shortly.")

    container_name = f"amination-forge-{secrets.token_hex(12)}"
    argv = [
        "docker", "run", "--name", container_name,
        "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--pids-limit", MAX_PIDS, "--memory", MAX_MEMORY,
        "--cpus", MAX_CPUS, "--user", "1000:1000",
        "--workdir", "/workspace",
        "--tmpfs", "/tmp:rw,nosuid,size=256m",
        "--mount", f"type=bind,src={directory},dst=/workspace",
        IMAGE, "/bin/sh", "-lc", command,
    ]

    process = None
    output = bytearray()
    output_lock = threading.Lock()
    reader = None
    timed_out = False
    exit_code = 1

    def collect_output(stream):
        # Keep only the newest MAX_OUTPUT bytes while output is being produced.
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                with output_lock:
                    output.extend(chunk)
                    if len(output) > MAX_OUTPUT:
                        del output[:-MAX_OUTPUT]
        except OSError:
            # The pipe can close while the process is being stopped.
            return

    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            shell=False,
            start_new_session=True,
        )
        reader = threading.Thread(
            target=collect_output, args=(process.stdout,), daemon=True
        )
        reader.start()

        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                process.wait()
            exit_code = 124
        finally:
            if reader is not None:
                # First allow the reader to consume EOF naturally.
                reader.join(timeout=5)

                if reader.is_alive() and process is not None:
                    # A descendant may still hold the output pipe open.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                    reader.join(timeout=2)

            if process is not None and process.stdout is not None:
                process.stdout.close()

            if reader is not None and reader.is_alive():
                reader.join(timeout=1)
                if reader.is_alive():
                    raise RunnerError(
                        "Runner output reader did not stop cleanly."
                    )

        with output_lock:
            rendered = bytes(output).decode("utf-8", errors="replace")

        if timed_out:
            rendered = (rendered + "\\n[Forge runner: execution timed out.]")[-MAX_OUTPUT:]

        return {
            "exit_code": exit_code,
            "output": rendered,
            "timed_out": timed_out,
            "duration_limit_seconds": timeout,
        }
    except FileNotFoundError as exc:
        raise RunnerError("Docker is not installed on the runner host.") from exc
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                process.wait(timeout=3)
            except Exception:
                pass

        # Explicit removal also cleans a container whose Docker CLI was killed.
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                shell=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        _execution_slots.release()


def _health_status() -> tuple[int, dict]:
    """Return a minimal readiness result without exposing host details."""
    unavailable = {
        "status": "degraded",
        "docker_available": False,
        "image_available": False,
    }
    try:
        daemon = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            shell=False,
        )
        if daemon.returncode != 0:
            return 503, unavailable

        image = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            shell=False,
        )
        if image.returncode != 0:
            return 503, {
                "status": "degraded",
                "docker_available": True,
                "image_available": False,
            }

        return 200, {
            "status": "ready",
            "docker_available": True,
            "image_available": True,
        }
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return 503, unavailable


class Handler(BaseHTTPRequestHandler):
    server_version = "AminationForgeRunner/1"

    def log_message(self, fmt: str, *args) -> None:
        # Do not log command text, file contents, or bearer credentials.
        print(f"[forge-runner] {self.client_address[0]} {fmt % args}")

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
        return bool(TOKEN) and hmac.compare_digest(supplied, expected)

    def _body(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise RunnerError("Invalid request size.") from exc
        if size < 1 or size > MAX_BODY:
            raise RunnerError("Request body is empty or too large.")
        try:
            value = json.loads(self.rfile.read(size))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunnerError("Invalid JSON request.") from exc
        if not isinstance(value, dict):
            raise RunnerError("A JSON object is required.")
        return value

    def _route(self) -> tuple[str, str | None, str]:
        parts = [unquote(x) for x in urlparse(self.path).path.split("/") if x]
        if len(parts) < 2 or parts[0] != "v1" or parts[1] != "sessions":
            raise RunnerError("Endpoint not found.")
        session_id = parts[2] if len(parts) >= 3 else None
        action = parts[3] if len(parts) >= 4 else ""
        return parts[1], session_id, action

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(401, {"error": "Unauthorized"})
            return
        try:
            _, session_id, action = self._route()
            body = self._body()

            if session_id is None and action == "":
                files = _safe_files(body.get("files"))
                session_id = secrets.token_hex(16)
                directory = Path(tempfile.mkdtemp(prefix="session-", dir=ROOT))
                try:
                    _write_files(directory, files)
                    with _lock:
                        _sessions[session_id] = directory
                        _session_last_used[session_id] = time.monotonic()
                except Exception:
                    shutil.rmtree(directory, ignore_errors=True)
                    raise
                self._json(201, {"session_id": session_id, "cwd": "/workspace"})
                return

            if action == "execute":
                active_id = session_id or ""
                directory = _begin_session_use(active_id)
                try:
                    result = _execute(
                        directory,
                        body.get("command"),
                        body.get("timeout_seconds", 30),
                    )
                finally:
                    _end_session_use(active_id)
                self._json(200, result)
                return
            directory = _workspace(session_id or "")

            self._json(404, {"error": "Endpoint not found"})
        except RunnerBusyError as exc:
            self._json(429, {"error": str(exc)})
        except RunnerError as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Runner operation failed"})

    def do_PUT(self) -> None:
        if not self._authorized():
            self._json(401, {"error": "Unauthorized"})
            return
        session_id = ""
        reserved = False
        try:
            _, parsed_session_id, action = self._route()
            if parsed_session_id is None or action != "files":
                self._json(404, {"error": "Endpoint not found"})
                return
            session_id = parsed_session_id
            body = self._body()
            files = _safe_files(body.get("files"))
            directory = _begin_session_use(session_id)
            reserved = True
            _replace_files(directory, files)
            self._json(200, {"updated": True, "file_count": len(files)})
        except RunnerBusyError as exc:
            self._json(409, {"error": str(exc)})
        except RunnerError as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Runner operation failed"})
        finally:
            if reserved:
                _end_session_use(session_id)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/healthz":
            status, payload = _health_status()
            self._json(status, payload)
            return
        if not self._authorized():
            self._json(401, {"error": "Unauthorized"})
            return
        session_id = ""
        reserved = False
        try:
            _, parsed_session_id, action = self._route()
            if parsed_session_id is None or action != "files":
                self._json(404, {"error": "Endpoint not found"})
                return
            session_id = parsed_session_id
            directory = _begin_session_use(session_id)
            reserved = True
            self._json(200, {"files": _read_files(directory)})
        except RunnerBusyError as exc:
            self._json(409, {"error": str(exc)})
        except RunnerError as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Runner operation failed"})
        finally:
            if reserved:
                _end_session_use(session_id)

    def do_DELETE(self) -> None:
        if not self._authorized():
            self._json(401, {"error": "Unauthorized"})
            return
        try:
            _, session_id, action = self._route()
            if session_id is None or action:
                self._json(404, {"error": "Endpoint not found"})
                return
            with _lock:
                if session_id in _active_sessions:
                    raise RunnerBusyError("Cannot close a session while another operation is using it.")
                directory = _sessions.get(session_id)
                if directory is None or not directory.is_dir():
                    raise RunnerError("Runner session not found.")
                _sessions.pop(session_id, None)
                _session_last_used.pop(session_id, None)
            shutil.rmtree(directory)
            self._json(200, {"closed": True})
        except RunnerBusyError as exc:
            self._json(409, {"error": str(exc)})
        except RunnerError as exc:
            self._json(404, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Runner operation failed"})


def main() -> None:
    if not TOKEN:
        raise SystemExit("FORGE_RUNNER_TOKEN must be configured.")
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise SystemExit("FORGE_RUNNER_ROOT must be a real directory.")
    host = os.getenv("FORGE_RUNNER_HOST", "127.0.0.1")
    port = int(os.getenv("FORGE_RUNNER_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    cleanup_thread = threading.Thread(target=_session_cleanup_loop, daemon=True)
    cleanup_thread.start()
    print(f"Amination Forge runner listening on {host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
