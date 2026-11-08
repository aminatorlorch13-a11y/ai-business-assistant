"""Tenant-scoped sessions for editing vaulted Forge candidates safely."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from app.forge.job_store import ForgeJobRecord
from app.forge.artifact_store import ForgeArtifactStore
from app.forge.job_store import ForgeJobStore
from app.forge.job import ForgeJobStatus
from app.forge.task_spec import ForgeTaskSpec
from app.forge.artifact_vault import ForgeArtifactVault
from app.forge.python_executor import ForgePythonCandidateExecutor
from app.forge.terminal import ForgeVirtualTerminal
from app.forge.verification import (
    build_candidate_verification_report,
    validate_candidate_verification_report,
)
from app.forge.worker import ForgeExecutionResult


_ARTIFACT_REF = re.compile(r"^forge-artifact://([0-9a-f]{32})$")
_MAX_ARTIFACT_BYTES = 3 * 1024 * 1024


class ForgeTerminalSessionError(RuntimeError):
    """A terminal session could not be safely opened or saved."""


@dataclass
class _TerminalSession:
    business_id: str
    project_id: str
    job_id: str
    artifact_reference: str
    workspace: Path
    terminal: ForgeVirtualTerminal
    spec: ForgeTaskSpec
    candidate: dict[str, Any]
    runner_session_id: str | None = None


class ForgeTerminalService:
    """Opens vaulted candidates in isolated, tenant-scoped virtual workspaces.

    The caller must perform normal user/tenant authorization before invoking
    this service. Identifiers supplied here are scope selectors, not credentials.
    """

    def __init__(
        self,
        job_store: ForgeJobStore,
        artifact_store: ForgeArtifactStore,
        artifact_vault: ForgeArtifactVault,
        workspace_root: str | Path | None = None,
        runner_client: Any | None = None,
    ) -> None:
        if not isinstance(job_store, ForgeJobStore):
            raise TypeError("job_store must be a ForgeJobStore.")
        if not isinstance(artifact_store, ForgeArtifactStore):
            raise TypeError("artifact_store must be a ForgeArtifactStore.")
        if not isinstance(artifact_vault, ForgeArtifactVault):
            raise TypeError("artifact_vault must be a ForgeArtifactVault.")

        self._jobs = job_store
        self._artifacts = artifact_store
        self._vault = artifact_vault
        self._runner = runner_client
        configured_root = (
            workspace_root
            if workspace_root is not None
            else os.getenv("FORGE_TERMINAL_WORKSPACE_PATH", "data/forge-workspaces")
        )
        self._root = Path(configured_root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self._root.is_dir():
            raise ForgeTerminalSessionError("Terminal workspace root is not a directory.")
        self._sessions: dict[tuple[str, str, str], _TerminalSession] = {}

    @staticmethod
    def _identity(business_id: str, project_id: str, job_id: str) -> tuple[str, str, str]:
        values = (business_id, project_id, job_id)
        if any(not isinstance(value, str) or not value or value != value.strip() for value in values):
            raise ValueError("A valid business, project and job identity is required.")
        if any(len(value) > 128 for value in values):
            raise ValueError("Forge identity value is too long.")
        return values

    def open_session(
        self, business_id: str, project_id: str, job_id: str
    ) -> dict[str, Any]:
        identity = self._identity(business_id, project_id, job_id)
        existing = self._sessions.get(identity)
        if existing is not None:
            return {
                "job_id": job_id,
                "artifact_reference": existing.artifact_reference,
                "cwd": existing.terminal.cwd,
                "commands": list(existing.terminal.COMMANDS),
                "reused": True,
            }

        record = self._jobs.get(*identity)
        if record is None:
            raise ForgeTerminalSessionError("Forge job was not found in this scope.")

        status = record.job.status
        status_value = status.value if hasattr(status, "value") else str(status)
        if status_value != ForgeJobStatus.COMPLETED_VAULTED.value:
            raise ForgeTerminalSessionError(
                "Only a completed, vaulted Forge candidate can be opened."
            )

        spec = self._jobs.get_task_spec(*identity)
        if not isinstance(spec, ForgeTaskSpec):
            raise ForgeTerminalSessionError("The immutable Forge task specification is missing.")

        checkpoint = record.job.checkpoint
        if not isinstance(checkpoint, Mapping):
            raise ForgeTerminalSessionError("The completed job has no artifact checkpoint.")
        artifact_reference = checkpoint.get("artifact_reference")
        if not isinstance(artifact_reference, str):
            raise ForgeTerminalSessionError("The job artifact reference is missing.")

        match = _ARTIFACT_REF.fullmatch(artifact_reference)
        if match is None:
            raise ForgeTerminalSessionError("The job contains an invalid artifact reference.")

        raw = self._artifacts.read(match.group(1), business_id, project_id)
        if raw is None or len(raw) > _MAX_ARTIFACT_BYTES:
            raise ForgeTerminalSessionError("The candidate artifact is unavailable or too large.")

        try:
            candidate = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ForgeTerminalSessionError("The candidate artifact is invalid.") from exc

        if not isinstance(candidate, dict):
            raise ForgeTerminalSessionError("The candidate artifact must be an object.")

        expected = {
            "format": "amination-forge-candidate-v1",
            "business_id": business_id,
            "project_id": project_id,
            "job_id": job_id,
            "language": spec.language,
        }
        for key, value in expected.items():
            if candidate.get(key) != value:
                raise ForgeTerminalSessionError(
                    f"Candidate {key} does not match its immutable task scope."
                )

        files = candidate.get("files")
        if not isinstance(files, Mapping):
            raise ForgeTerminalSessionError("Candidate files are missing.")

        try:
            safe_files = ForgePythonCandidateExecutor._validate_files(files)
            validate_candidate_verification_report(
                safe_files, candidate.get("verification")
            )
        except Exception as exc:
            raise ForgeTerminalSessionError(
                "Candidate file or verification validation failed."
            ) from exc

        workspace = Path(tempfile.mkdtemp(prefix="forge-session-", dir=self._root))
        try:
            for relative_name, content in safe_files.items():
                relative = PurePosixPath(relative_name)
                target = workspace.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8", newline="") as handle:
                    handle.write(content)

            terminal = ForgeVirtualTerminal(workspace)
            runner_session_id = None
            if self._runner is not None:
                runner_session_id = self._runner.open_session(safe_files)
            session = _TerminalSession(
                business_id=business_id,
                project_id=project_id,
                job_id=job_id,
                artifact_reference=artifact_reference,
                workspace=workspace,
                terminal=terminal,
                spec=spec,
                candidate=dict(candidate),
                runner_session_id=runner_session_id,
            )
            self._sessions[identity] = session
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

        return {
            "job_id": job_id,
            "artifact_reference": artifact_reference,
            "cwd": terminal.cwd,
            "commands": list(terminal.COMMANDS),
            "reused": False,
        }

    def _workspace_snapshot(self, session: _TerminalSession) -> dict[str, str]:
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

    def save_session(
        self, business_id: str, project_id: str, job_id: str
    ) -> dict[str, Any]:
        identity = self._identity(business_id, project_id, job_id)
        session = self._sessions.get(identity)
        if session is None:
            raise ForgeTerminalSessionError("Open the Forge terminal session first.")

        files: dict[str, str] = {}
        for path in sorted(session.workspace.rglob("*")):
            if path.is_symlink():
                raise ForgeTerminalSessionError("Symbolic links are not allowed in a Forge workspace.")
            if not path.is_file():
                continue
            relative = path.relative_to(session.workspace).as_posix()
            try:
                files[relative] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ForgeTerminalSessionError(
                    f"Workspace file cannot be safely read: {relative}"
                ) from exc

        safe_files = ForgePythonCandidateExecutor._validate_files(files)
        checks = ForgePythonCandidateExecutor._static_checks(safe_files)
        failed = [item for item in checks if item["status"] == "fail"]
        if failed:
            names = ", ".join(item["file"] for item in failed)
            raise ForgeTerminalSessionError(
                f"Save blocked because static validation failed for: {names}"
            )

        report = build_candidate_verification_report(safe_files, checks)
        candidate = dict(session.candidate)
        candidate.update({
            "files": safe_files,
            "checks": checks,
            "verification": report,
            "parent_artifact_reference": session.artifact_reference,
            "candidate_revision": int(candidate.get("candidate_revision", 1)) + 1,
            "execution_policy": {
                "generated_code_executed": False,
                "live_repository_modified": False,
                "shell_commands_invoked": False,
            },
        })

        # Store the immutable artifact first. It is not made current until
        # the job checkpoint is updated with optimistic concurrency protection.
        artifact_reference = self._vault(
            session.spec, ForgeExecutionResult(candidate=candidate)
        )

        current_record = self._jobs.get(
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
        )
        if current_record is None:
            raise ForgeTerminalSessionError(
                "The Forge job no longer exists; the saved artifact was not attached."
            )

        current_status = getattr(
            current_record.job.status, "value", current_record.job.status
        )
        if current_status != "completed_vaulted":
            raise ForgeTerminalSessionError(
                "The Forge job is no longer in a state that permits terminal saves."
            )

        checkpoint = dict(current_record.job.checkpoint or {})
        if checkpoint.get("artifact_reference") != session.artifact_reference:
            raise ForgeTerminalSessionError(
                "This terminal session is stale. A newer artifact revision already exists."
            )

        checkpoint.update({
            "artifact_reference": artifact_reference,
            "candidate_revision": candidate["candidate_revision"],
            "parent_artifact_reference": candidate["parent_artifact_reference"],
        })

        now = datetime.now(timezone.utc)
        updated_at = max(now, current_record.job.updated_at)

        updated_job = replace(
            current_record.job,
            checkpoint=checkpoint,
            updated_at=updated_at,
        )
        updated_record = ForgeJobRecord(
            job=updated_job,
            revision=current_record.revision,
            worker_id=current_record.worker_id,
            lease_expires_at=current_record.lease_expires_at,
            lease_generation=current_record.lease_generation,
        )

        # The store performs a revision/lease-generation compare-and-swap.
        # If another update won the race, this save fails safely.
        self._jobs.update(updated_record)

        # Update the in-memory session only after the durable pointer succeeds.
        session.artifact_reference = artifact_reference
        session.candidate = candidate

        return {
            "job_id": job_id,
            "artifact_reference": artifact_reference,
            "parent_artifact_reference": candidate["parent_artifact_reference"],
            "verification_status": report["static_analysis"]["status"],
            "execution_enabled": False,
            "live_repository_modified": False,
        }

    def close_session(
        self, business_id: str, project_id: str, job_id: str
    ) -> bool:
        identity = self._identity(business_id, project_id, job_id)
        session = self._sessions.pop(identity, None)
        if session is None:
            return False

        try:
            if self._runner is not None and session.runner_session_id is not None:
                self._runner.close_session(session.runner_session_id)
        finally:
            shutil.rmtree(session.workspace, ignore_errors=True)

        return True

    def close_all(self) -> None:
        for identity in list(self._sessions):
            self.close_session(*identity)
