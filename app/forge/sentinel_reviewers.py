"""Five fail-closed static reviewers for Amination Forge Sentinel."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from app.forge.sentinel_guards import (
    GUARD_IDS, GuardDecision, GuardInput, GuardReviewer, GuardVerdict,
)
from app.forge.verification import validate_candidate_verification_report

IMPLEMENTATION_IDS = (
    "amination.sentinel.guard1.envelope.v1",
    "amination.sentinel.guard2.paths.v1",
    "amination.sentinel.guard3.secrets-and-text.v1",
    "amination.sentinel.guard4.verification.v1",
    "amination.sentinel.guard5.acceptance-boundary.v1",
)

SECRET_PATTERNS = tuple(re.compile(p) for p in (
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
    r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
    r"\bAIza[0-9A-Za-z_-]{30,}\b",
))


def result(verdict: GuardVerdict, message: str) -> GuardDecision:
    return GuardDecision(verdict=verdict, findings=(message[:2000],))


def candidate(data: GuardInput) -> Mapping[str, Any]:
    if not isinstance(data.candidate_bytes, bytes) or not data.candidate_bytes:
        raise ValueError("Candidate artifact is empty.")

    def unique_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate JSON object key.")
            obj[key] = value
        return obj

    def reject_constant(value):
        raise ValueError(f"Invalid JSON numeric constant: {value}")

    try:
        value = json.loads(
            data.candidate_bytes.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Candidate is not valid UTF-8 JSON.") from exc

    if not isinstance(value, Mapping):
        raise ValueError("Candidate root must be an object.")
    return value


def guard1(data: GuardInput) -> GuardDecision:
    try:
        c = candidate(data)
        if c.get("format") != "amination-forge-candidate-v1":
            return result(GuardVerdict.FAIL, "Unsupported candidate format.")
        for key in ("business_id", "project_id", "job_id"):
            value = c.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                return result(GuardVerdict.FAIL, f"Invalid candidate identity: {key}.")
        if not isinstance(c.get("files"), Mapping) or not c["files"]:
            return result(GuardVerdict.FAIL, "Candidate files are missing.")
        if not isinstance(c.get("verification"), Mapping):
            return result(GuardVerdict.FAIL, "Verification report is missing.")
        return result(GuardVerdict.PASS, "Candidate envelope and identity are valid.")
    except (TypeError, ValueError) as exc:
        return result(GuardVerdict.FAIL, str(exc))


def guard2(data: GuardInput) -> GuardDecision:
    try:
        files = candidate(data).get("files")
        if not isinstance(files, Mapping) or not files:
            return result(GuardVerdict.FAIL, "Candidate files are missing.")
        seen = set()
        for name, content in files.items():
            if not isinstance(name, str) or not name or not isinstance(content, str):
                return result(GuardVerdict.FAIL, "File paths and contents must be text.")
            path = PurePosixPath(name)
            parts = name.split("/")
            if (
                path.is_absolute() or "\\" in name or "\x00" in name
                or any(p in {"", ".", ".."} for p in parts)
                or str(path) != name
                or (len(name) > 1 and name[1] == ":")
            ):
                return result(GuardVerdict.FAIL, f"Unsafe file path: {name[:180]}")
            folded = name.casefold()
            if folded in seen:
                return result(GuardVerdict.FAIL, f"Case-insensitive path collision: {name[:180]}")
            seen.add(folded)
        return result(GuardVerdict.PASS, "All file paths are relative and canonical.")
    except (TypeError, ValueError) as exc:
        return result(GuardVerdict.FAIL, str(exc))


def guard3(data: GuardInput) -> GuardDecision:
    try:
        files = candidate(data).get("files")
        if not isinstance(files, Mapping) or not files:
            return result(GuardVerdict.FAIL, "Candidate files are missing.")
        for name, content in files.items():
            if not isinstance(name, str) or not isinstance(content, str):
                return result(GuardVerdict.FAIL, "Candidate files must contain text.")
            if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in content):
                return result(GuardVerdict.FAIL, f"Binary/control data found in {name[:180]}.")
            if any(pattern.search(content) for pattern in SECRET_PATTERNS):
                return result(GuardVerdict.FAIL, f"Potential embedded credential in {name[:180]}.")
        return result(GuardVerdict.PASS, "No supported high-confidence secret patterns or binary control data found.")
    except (TypeError, ValueError) as exc:
        return result(GuardVerdict.FAIL, str(exc))


def guard4(data: GuardInput) -> GuardDecision:
    try:
        c = candidate(data)
        files, report = c.get("files"), c.get("verification")
        if not isinstance(files, Mapping) or not isinstance(report, Mapping):
            return result(GuardVerdict.FAIL, "Files or verification evidence is missing.")
        validate_candidate_verification_report(files, report)
        status = report["static_analysis"]["status"]
        if status == "fail":
            return result(GuardVerdict.FAIL, "Static analysis reports failures.")
        if status != "pass":
            return result(GuardVerdict.INCONCLUSIVE, "Static checks do not cover every file with passing results.")
        return result(GuardVerdict.PASS, "Verification report and file digests are consistent.")
    except (TypeError, ValueError, KeyError) as exc:
        return result(GuardVerdict.FAIL, f"Verification evidence rejected: {exc}")


def guard5(data: GuardInput) -> GuardDecision:
    try:
        report = candidate(data).get("verification")
        if not isinstance(report, Mapping):
            return result(GuardVerdict.FAIL, "Verification report is missing.")
        readiness = report.get("readiness")
        statuses = report.get("gate_status")
        limitations = report.get("limitations")
        if not isinstance(readiness, Mapping) or not isinstance(statuses, Mapping):
            return result(GuardVerdict.FAIL, "Acceptance/release evidence is malformed.")
        if readiness.get("production_ready") is not False:
            return result(GuardVerdict.FAIL, "Candidate improperly claims production readiness.")
        if readiness.get("release_authorized") is not False:
            return result(GuardVerdict.FAIL, "Candidate improperly claims release authorization.")
        required_gates = {
            "self_verification", "independent_review", "user_acceptance", "release"
        }
        if set(statuses) != required_gates or any(v != "blocked" for v in statuses.values()):
            return result(GuardVerdict.FAIL, "Acceptance and release gates must remain blocked.")
        disclosures = (
            "Build, unit, integration, regression and runtime tests were not run.",
            "Security, privacy, legal, accessibility and maintainability reviews were not performed.",
            "Human user acceptance has not been recorded.",
            "No release or deployment has been authorized.",
        )
        if not isinstance(limitations, list) or any(x not in limitations for x in disclosures):
            return result(GuardVerdict.INCONCLUSIVE, "Required test, review and release limitations are not disclosed.")
        return result(GuardVerdict.PASS, "User acceptance remains separate from release authorization.")
    except (TypeError, ValueError) as exc:
        return result(GuardVerdict.FAIL, str(exc))


def build_production_sentinel_reviewers() -> tuple[GuardReviewer, ...]:
    checks = (guard1, guard2, guard3, guard4, guard5)
    return tuple(
        GuardReviewer(guard_id, implementation_id, check)
        for guard_id, implementation_id, check in zip(
            GUARD_IDS, IMPLEMENTATION_IDS, checks, strict=True
        )
    )
