from pathlib import Path

p = Path("app/forge/runner/server.py")
s = p.read_text()

def replace_once(old, new, label):
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"STOP: expected one match for {label}; found {count}. No file written.")
    s = s.replace(old, new, 1)

replace_once(
    "import re\nimport secrets\nimport shutil\nimport subprocess\nimport tempfile\nimport threading\n",
    "import re\nimport secrets\nimport shutil\nimport signal\nimport subprocess\nimport tempfile\nimport threading\nimport time\n",
    "imports",
)

replace_once(
    'MAX_TIMEOUT = int(os.getenv("FORGE_RUNNER_MAX_TIMEOUT", "120"))\n\n# The runner root is created by main(), not during module import.\n_lock = threading.RLock()\n_sessions: dict[str, Path] = {}\n',
    '''MAX_TIMEOUT = int(os.getenv("FORGE_RUNNER_MAX_TIMEOUT", "120"))
MAX_CONCURRENT_EXECUTIONS = max(1, int(os.getenv("FORGE_RUNNER_MAX_CONCURRENT", "2")))
SESSION_IDLE_TTL_SECONDS = max(60, int(os.getenv("FORGE_RUNNER_SESSION_TTL", "1800")))
SESSION_CLEANUP_INTERVAL_SECONDS = 60

# The runner root is created by main(), not during module import.
_lock = threading.RLock()
_sessions: dict[str, Path] = {}
_session_last_used: dict[str, float] = {}
_active_sessions: set[str] = set()
_execution_slots = threading.BoundedSemaphore(MAX_CONCURRENT_EXECUTIONS)
''',
    "runner limits and session state",
)

replace_once(
    "class RunnerError(Exception):\n    pass\n\n\ndef _safe_files",
    "class RunnerError(Exception):\n    pass\n\n\nclass RunnerBusyError(RunnerError):\n    pass\n\n\ndef _safe_files",
    "busy exception",
)

start = s.index("def _workspace(session_id: str) -> Path:")
end = s.index("\n\nclass Handler(BaseHTTPRequestHandler):", start)

replacement = '''def _workspace(session_id: str) -> Path:
    if not SESSION_RE.fullmatch(session_id):
        raise RunnerError("Invalid runner session identifier.")
    with _lock:
        path = _sessions.get(session_id)
        if path is None or not path.is_dir():
            raise RunnerError("Runner session not found.")
        _session_last_used[session_id] = time.monotonic()
    return path


def _begin_execution(session_id: str) -> Path:
    """Atomically protect a session from expiry while a command is running."""
    if not SESSION_RE.fullmatch(session_id):
        raise RunnerError("Invalid runner session identifier.")
    with _lock:
        path = _sessions.get(session_id)
        if path is None or not path.is_dir():
            raise RunnerError("Runner session not found.")
        if session_id in _active_sessions:
            raise RunnerBusyError("A command is already running in this session.")
        _active_sessions.add(session_id)
        _session_last_used[session_id] = time.monotonic()
        return path


def _end_execution(session_id: str) -> None:
    with _lock:
        _active_sessions.discard(session_id)
        if session_id in _sessions:
            _session_last_used[session_id] = time.monotonic()


def _cleanup_expired_sessions(now: float | None = None) -> int:
    """Remove idle workspaces but never remove one with active execution."""
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
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            with output_lock:
                output.extend(chunk)
                if len(output) > MAX_OUTPUT:
                    del output[:-MAX_OUTPUT]

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
            if process.stdout is not None:
                process.stdout.close()
            if reader is not None:
                reader.join(timeout=2)

        with output_lock:
            rendered = bytes(output).decode("utf-8", errors="replace")

        if timed_out:
            rendered = (rendered + "\\\\n[Forge runner: execution timed out.]")[-MAX_OUTPUT:]

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
'''

s = s[:start] + replacement + s[end:]

replace_once(
    "                    with _lock:\n                        _sessions[session_id] = directory\n",
    "                    with _lock:\n                        _sessions[session_id] = directory\n                        _session_last_used[session_id] = time.monotonic()\n",
    "session creation timestamp",
)

replace_once(
    '''            directory = _workspace(session_id or "")
            if action == "execute":
                result = _execute(
                    directory,
                    body.get("command"),
                    body.get("timeout_seconds", 30),
                )
                self._json(200, result)
                return
''',
    '''            if action == "execute":
                active_id = session_id or ""
                directory = _begin_execution(active_id)
                try:
                    result = _execute(
                        directory,
                        body.get("command"),
                        body.get("timeout_seconds", 30),
                    )
                finally:
                    _end_execution(active_id)
                self._json(200, result)
                return
            directory = _workspace(session_id or "")
''',
    "execution session protection",
)

replace_once(
    '''        except RunnerError as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Runner operation failed"})

    def do_PUT''',
    '''        except RunnerBusyError as exc:
            self._json(429, {"error": str(exc)})
        except RunnerError as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Runner operation failed"})

    def do_PUT''',
    "retryable busy response",
)

replace_once(
    '''            directory = _workspace(session_id)
            with _lock:
                _sessions.pop(session_id, None)
            shutil.rmtree(directory)
            self._json(200, {"closed": True})
        except RunnerError as exc:
            self._json(404, {"error": str(exc)})
''',
    '''            with _lock:
                if session_id in _active_sessions:
                    raise RunnerBusyError("Cannot close a session while a command is running.")
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
''',
    "safe session close",
)

replace_once(
    '''    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Amination Forge runner listening on {host}:{port}")
    server.serve_forever()
''',
    '''    server = ThreadingHTTPServer((host, port), Handler)
    cleanup_thread = threading.Thread(target=_session_cleanup_loop, daemon=True)
    cleanup_thread.start()
    print(f"Amination Forge runner listening on {host}:{port}")
    server.serve_forever()
''',
    "cleanup worker startup",
)

# Only write after every expected source section has matched.
p.write_text(s)
print("Runner hardening patch installed.")
