from __future__ import annotations

import ast
import json
import tomllib
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from app.forge.languages import ALLOWED_SUFFIXES
from app.forge.task_spec import ForgeTaskSpec
from app.forge.verification import build_candidate_verification_report
from app.forge.toolchains import build_toolchain_plan
from app.forge.worker import ForgeExecutionContext, ForgeExecutionResult

MAX_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024


class ForgeCandidateValidationError(ValueError):
    """A proposed candidate contains unsafe or invalid file content."""


class ForgePythonCandidateExecutor:
    """Validate generated candidate files without executing generated code."""

    def __init__(
        self,
        generate: Callable[
            [ForgeTaskSpec, ForgeExecutionContext],
            Mapping[str, str],
        ],
    ) -> None:
        if not callable(generate):
            raise TypeError("generate must be callable.")
        self._generate = generate

    def __call__(
        self,
        spec: ForgeTaskSpec,
        context: ForgeExecutionContext,
    ) -> ForgeExecutionResult:
        if not isinstance(spec, ForgeTaskSpec):
            raise TypeError("spec must be a ForgeTaskSpec.")
        if not isinstance(context, ForgeExecutionContext):
            raise TypeError("context must be a ForgeExecutionContext.")

        context.check_cancellation()
        proposed = self._generate(spec, context)
        files = self._validate_files(proposed)
        context.check_cancellation()
        context.report_progress(70, "candidate_validated")

        checks = self._static_checks(files)
        failed = [item for item in checks if item["status"] == "fail"]
        if failed:
            names = ", ".join(item["file"] for item in failed)
            raise ForgeCandidateValidationError(
                f"Static validation failed for: {names}"
            )

        report = build_candidate_verification_report(files, checks)
        return ForgeExecutionResult(
            candidate={
                "format": "amination-forge-candidate-v1",
                "business_id": spec.business_id,
                "project_id": spec.project_id,
                "job_id": spec.job_id,
                "language": spec.language,
                "toolchain_plan": build_toolchain_plan(spec.language),
                "files": files,
                "checks": checks,
                "verification": report,
                "execution_policy": {
                    "generated_code_executed": False,
                    "live_repository_modified": False,
                    "shell_commands_invoked": False,
                },
            }
        )

    @staticmethod
    def _validate_files(proposed: Mapping[str, str]) -> dict[str, str]:
        if not isinstance(proposed, Mapping):
            raise ForgeCandidateValidationError(
                "Generator must return a mapping of relative paths to text."
            )
        if not proposed or len(proposed) > MAX_FILES:
            raise ForgeCandidateValidationError(
                f"Candidate must contain between 1 and {MAX_FILES} files."
            )

        files: dict[str, str] = {}
        total = 0

        for raw_path, content in proposed.items():
            if not isinstance(raw_path, str) or not raw_path:
                raise ForgeCandidateValidationError(
                    "Every candidate path must be a non-empty string."
                )
            if not isinstance(content, str):
                raise ForgeCandidateValidationError(
                    f"Candidate file {raw_path!r} must contain text."
                )

            path = PurePosixPath(raw_path)
            segments = raw_path.split("/")
            has_control_chars = any(
                ord(char) < 32 or ord(char) == 127 for char in raw_path
            )
            if (
                path.is_absolute()
                or "\\" in raw_path
                or any(part in {"", ".", ".."} for part in segments)
                or has_control_chars
                or ":" in segments[0]
                or path.suffix.lower() not in ALLOWED_SUFFIXES
            ):
                raise ForgeCandidateValidationError(
                    f"Unsafe or unsupported candidate path: {raw_path!r}"
                )

            normalized = path.as_posix()
            if normalized in files:
                raise ForgeCandidateValidationError(
                    f"Duplicate candidate path: {normalized}"
                )

            size = len(content.encode("utf-8"))
            if size > MAX_FILE_BYTES:
                raise ForgeCandidateValidationError(
                    f"Candidate file exceeds {MAX_FILE_BYTES} bytes: {normalized}"
                )
            total += size
            if total > MAX_TOTAL_BYTES:
                raise ForgeCandidateValidationError(
                    f"Candidate exceeds total size limit of {MAX_TOTAL_BYTES} bytes."
                )
            files[normalized] = content

        return files

    @staticmethod
    def _static_checks(files: Mapping[str, str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for name, content in sorted(files.items()):
            suffix = PurePosixPath(name).suffix.lower()
            status = "pass"
            message = "Text content accepted; no code execution performed."

            try:
                if suffix == ".py":
                    ast.parse(content, filename=name)
                    message = "Python syntax parsed successfully; code was not executed."
                elif suffix == ".json":
                    json.loads(content)
                    message = "JSON parsed successfully."
                elif suffix == ".toml":
                    tomllib.loads(content)
                    message = "TOML parsed successfully."
                elif suffix == ".xml":
                    ET.fromstring(content)
                    message = "XML parsed successfully."
                elif suffix in {".html", ".htm"}:
                    parser = HTMLParser()
                    parser.feed(content)
                    parser.close()
                    message = "HTML tokenized successfully; browser rendering was not tested."
                elif suffix in {".md", ".txt"}:
                    message = "Text content accepted; language semantics were not checked."
                else:
                    status = "inconclusive"
                    message = (
                        f"No trusted static checker is configured for {suffix}; "
                        "syntax and behaviour remain unverified."
                    )
            except (SyntaxError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
                status = "fail"
                message = str(exc)[:500]

            results.append({
                "file": name,
                "check": "static_syntax",
                "status": status,
                "passed": status == "pass",
                "message": message,
            })

        return results
