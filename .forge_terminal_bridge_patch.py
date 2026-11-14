from pathlib import Path

def patch(path, replacements):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in s:
            raise SystemExit(f"STOP: expected code not found in {path}:\n{old[:180]}")
        s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")
    print(f"Patched {path}")

# 1. Runner client: strict URL validation and workspace synchronisation.
patch("app/forge/runner/client.py", [
    (
        "import json\nimport urllib.error\nimport urllib.request\n",
        "import json\nimport re\nimport urllib.error\nimport urllib.request\nfrom urllib.parse import urlsplit\n",
    ),
    (
        '''    def __init__(self, base_url: str, token: str, timeout: int = 20):
        if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1"):
            raise ValueError("The Forge runner URL must use HTTPS.")
        if not token:
            raise ValueError("A Forge runner token is required.")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
''',
        '''    def __init__(self, base_url: str, token: str, timeout: int = 20):
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
''',
    ),
    (
        '''        session_id = result.get("session_id")
        if not isinstance(session_id, str) or len(session_id) != 32:
            raise ForgeRunnerClientError("The runner did not return a valid session.")
        return session_id
''',
        '''        session_id = result.get("session_id")
        try:
            return self._validate_session_id(session_id)
        except ValueError as exc:
            raise ForgeRunnerClientError(
                "The runner did not return a valid session."
            ) from exc
''',
    ),
    (
        '''    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        import re
        if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
''',
        '''    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
''',
    ),
    (
        '''    def read_files(self, session_id: str) -> dict[str, str]:
''',
        '''    def sync_files(self, session_id: str, files: dict[str, str]) -> None:
        session_id = self._validate_session_id(session_id)
        if not isinstance(files, dict):
            raise ValueError("Runner workspace files must be a dictionary.")
        self._request("PUT", f"/v1/sessions/{session_id}/files", {"files": files})

    def read_files(self, session_id: str) -> dict[str, str]:
''',
    ),
])

# 2. Runner server: avoid import-time filesystem writes and add safe file replacement.
patch("app/forge/runner/server.py", [
    (
        "ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)",
        "# The runner root is created by main(), not during module import.",
    ),
    (
        '''def _read_files(directory: Path) -> dict[str, str]:
''',
        '''def _replace_files(directory: Path, files: dict[str, str]) -> None:
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
''',
    ),
    (
        '''    def do_GET(self) -> None:
''',
        '''    def do_PUT(self) -> None:
        if not self._authorized():
            self._json(401, {"error": "Unauthorized"})
            return
        try:
            _, session_id, action = self._route()
            if session_id is None or action != "files":
                self._json(404, {"error": "Endpoint not found"})
                return
            body = self._body()
            files = _safe_files(body.get("files"))
            _replace_files(_workspace(session_id), files)
            self._json(200, {"updated": True, "file_count": len(files)})
        except RunnerError as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Runner operation failed"})

    def do_GET(self) -> None:
''',
    ),
    (
        '''def main() -> None:
    if not TOKEN:
        raise SystemExit("FORGE_RUNNER_TOKEN must be configured.")
''',
        '''def main() -> None:
    if not TOKEN:
        raise SystemExit("FORGE_RUNNER_TOKEN must be configured.")
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise SystemExit("FORGE_RUNNER_ROOT must be a real directory.")
''',
    ),
])

# 3. Terminal: register the run command. The service intercepts it and routes
# it to the independent runner; the virtual terminal itself never runs it.
patch("app/forge/terminal.py", [
    (
        '"check", "build", "test",',
        '"check", "build", "test", "run",',
    ),
    (
        '''        if name in {"check", "build", "test"}:
''',
        '''        if name == "run":
            raise ForgeTerminalError(
                "RUN BLOCKED: connect the trusted independent Linux runner through "
                "ForgeTerminalService. No code was executed locally."
            )

        if name in {"check", "build", "test"}:
''',
    ),
])

# 4. Terminal service: optional runner, remote execution and safe file sync.
patch("app/forge/terminal_service.py", [
    (
        '''    candidate: dict[str, Any]


class ForgeTerminalService:
''',
        '''    candidate: dict[str, Any]
    runner_session_id: str | None = None


class ForgeTerminalService:
''',
    ),
    (
        '''        workspace_root: str | Path | None = None,
    ) -> None:
''',
        '''        workspace_root: str | Path | None = None,
        runner_client: Any | None = None,
    ) -> None:
''',
    ),
    (
        '''        self._vault = artifact_vault
        configured_root = (
''',
        '''        self._vault = artifact_vault
        self._runner = runner_client
        configured_root = (
''',
    ),
    (
        '''            terminal = ForgeVirtualTerminal(workspace)
            session = _TerminalSession(
''',
        '''            terminal = ForgeVirtualTerminal(workspace)
            runner_session_id = None
            if self._runner is not None:
                runner_session_id = self._runner.open_session(safe_files)
            session = _TerminalSession(
''',
    ),
    (
        '''                spec=spec,
                candidate=dict(candidate),
            )
''',
        '''                spec=spec,
                candidate=dict(candidate),
                runner_session_id=runner_session_id,
            )
''',
    ),
    (
        '''    def execute(
        self, business_id: str, project_id: str, job_id: str, command: str
    ) -> dict[str, Any]:
        identity = self._identity(business_id, project_id, job_id)
        session = self._sessions.get(identity)
        if session is None:
            raise ForgeTerminalSessionError("Open the Forge terminal session first.")
        return session.terminal.execute(command).to_dict()
''',
        '''    def _workspace_snapshot(self, session: _TerminalSession) -> dict[str, str]:
        files: dict[str, str] = {}
        total = 0
        for path in sorted(session.workspace.rglob("*")):
            if path.is_symlink():
                raise ForgeTerminalSessionError(
                    "Symbolic links are not allowed in a Forge workspace."
                )
            if not path.is_file():
                continue
            relative = path.relative_to(session.workspace).as_posix()
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ForgeTerminalSessionError(
                    f"Workspace file cannot be safely read: {relative}"
                ) from exc
            total += len(content.encode("utf-8"))
            if total > _MAX_ARTIFACT_BYTES:
                raise ForgeTerminalSessionError("Workspace exceeds the save size limit.")
            files[relative] = content
        try:
            return ForgePythonCandidateExecutor._validate_files(files)
        except Exception as exc:
            raise ForgeTerminalSessionError("Workspace file validation failed.") from exc

    def _apply_runner_snapshot(
        self, session: _TerminalSession, remote_files: Mapping[str, str]
    ) -> None:
        try:
            safe_files = ForgePythonCandidateExecutor._validate_files(remote_files)
        except Exception as exc:
            raise ForgeTerminalSessionError(
                "The runner returned an invalid workspace snapshot."
            ) from exc

        for child in session.workspace.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
            else:
                raise ForgeTerminalSessionError("Unsupported workspace entry.")

        for name, content in safe_files.items():
            relative = PurePosixPath(name)
            target = session.workspace.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8", newline="") as handle:
                handle.write(content)

    def execute(
        self, business_id: str, project_id: str, job_id: str, command: str
    ) -> dict[str, Any]:
        identity = self._identity(business_id, project_id, job_id)
        session = self._sessions.get(identity)
        if session is None:
            raise ForgeTerminalSessionError("Open the Forge terminal session first.")

        raw = command.strip() if isinstance(command, str) else ""
        parts = raw.split(None, 1)
        if parts and parts[0] == "run":
            if len(parts) != 2 or not parts[1].strip():
                return {
                    "command": command, "output": "Usage: run <Linux command>",
                    "exit_code": 2, "cwd": session.terminal.cwd, "ok": False,
                }
            if self._runner is None or session.runner_session_id is None:
                return {
                    "command": command,
                    "output": "RUN BLOCKED: trusted independent Linux runner is not connected. "
                              "No code was executed.",
                    "exit_code": 2, "cwd": session.terminal.cwd, "ok": False,
                }

            try:
                self._runner.sync_files(
                    session.runner_session_id, self._workspace_snapshot(session)
                )
                result = self._runner.execute(
                    session.runner_session_id, parts[1], timeout_seconds=30
                )
                remote_files = self._runner.read_files(session.runner_session_id)
                self._apply_runner_snapshot(session, remote_files)
            except Exception as exc:
                raise ForgeTerminalSessionError(
                    f"Isolated runner operation failed: {exc}"
                ) from exc

            if not isinstance(result, dict):
                raise ForgeTerminalSessionError("Runner returned an invalid execution result.")
            output = result.get("output", "")
            exit_code = result.get("exit_code", 1)
            if not isinstance(output, str) or not isinstance(exit_code, int):
                raise ForgeTerminalSessionError("Runner returned an invalid execution result.")
            return {
                "command": command,
                "output": output,
                "exit_code": exit_code,
                "cwd": session.terminal.cwd,
                "ok": exit_code == 0,
                "timed_out": bool(result.get("timed_out", False)),
                "execution_environment": "isolated_linux_runner",
            }

        return session.terminal.execute(command).to_dict()
''',
    ),
])

print("Forge terminal-to-runner bridge patch completed.")
