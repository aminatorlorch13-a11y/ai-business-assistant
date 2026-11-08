from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.forge.engineering_standard import ForgeStage, REQUIRED_GATE_EVIDENCE

REPORT_SCHEMA = "amination-forge-verification-v1"
STATIC_VALIDATOR = "amination-forge-multi-language-static-validator"
STATIC_VALIDATOR_VERSION = "2"

RELEASE_GATES = (
    ForgeStage.SELF_VERIFICATION,
    ForgeStage.INDEPENDENT_REVIEW,
    ForgeStage.USER_ACCEPTANCE,
    ForgeStage.RELEASE,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_status(check: Mapping[str, Any]) -> str:
    status = check.get("status")
    passed = check.get("passed")

    if status is None:
        if type(passed) is not bool:
            raise TypeError("Static check passed value must be a bool.")
        return "pass" if passed else "fail"

    if status not in {"pass", "fail", "inconclusive"}:
        raise ValueError("Static check status is invalid.")
    if passed is not None and type(passed) is not bool:
        raise TypeError("Static check passed value must be a bool.")
    if passed is not None and passed != (status == "pass"):
        raise ValueError("Static check passed flag conflicts with its status.")
    return status


def build_candidate_verification_report(
    files: Mapping[str, str],
    static_checks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic report without claiming unrun checks."""
    if not isinstance(files, Mapping) or not files:
        raise ValueError("files must be a non-empty mapping.")
    if not isinstance(static_checks, Sequence) or isinstance(
        static_checks, (str, bytes)
    ):
        raise TypeError("static_checks must be a sequence of check mappings.")

    canonical_files: dict[str, str] = {}
    for name, content in files.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Every candidate file needs a non-empty path.")
        if not isinstance(content, str):
            raise TypeError(f"Candidate file {name!r} must contain text.")
        canonical_files[name] = content

    file_payload = json.dumps(
        canonical_files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    candidate_digest = _sha256(file_payload)

    results: list[dict[str, Any]] = []
    seen_files: set[str] = set()

    for check in static_checks:
        if not isinstance(check, Mapping):
            raise TypeError("Every static check must be a mapping.")

        name = check.get("file")
        message = check.get("message")
        if name not in canonical_files:
            raise ValueError("Static check refers to an unknown candidate file.")
        if name in seen_files:
            raise ValueError(f"Duplicate static check for {name!r}.")
        if not isinstance(message, str):
            raise TypeError("Static check message must be a string.")

        status = _check_status(check)
        seen_files.add(name)
        results.append({
            "file": name,
            "check": check.get("check", "static_syntax"),
            "status": status,
            "input_sha256": _sha256(
                canonical_files[name].encode("utf-8")
            ),
            "message": message[:500],
        })

    results.sort(key=lambda item: item["file"])
    statuses = [item["status"] for item in results]
    static_status = (
        "inconclusive"
        if seen_files != set(canonical_files)
        else "fail"
        if "fail" in statuses
        else "inconclusive"
        if "inconclusive" in statuses
        else "pass"
    )

    gate_evidence = {
        stage.value: {
            requirement: "not_run"
            for requirement in sorted(REQUIRED_GATE_EVIDENCE[stage])
        }
        for stage in RELEASE_GATES
    }
    gate_status = {
        stage: (
            "blocked"
            if any(value != "pass" for value in requirements.values())
            else "passed"
        )
        for stage, requirements in gate_evidence.items()
    }

    return {
        "schema": REPORT_SCHEMA,
        "candidate_files_sha256": candidate_digest,
        "static_analysis": {
            "status": static_status,
            "tool": STATIC_VALIDATOR,
            "tool_version": STATIC_VALIDATOR_VERSION,
            "checks": results,
        },
        "gate_evidence": gate_evidence,
        "gate_status": gate_status,
        "readiness": {
            "candidate_validation": static_status,
            "self_verification": gate_status[ForgeStage.SELF_VERIFICATION.value],
            "independent_review": gate_status[ForgeStage.INDEPENDENT_REVIEW.value],
            "user_acceptance": gate_status[ForgeStage.USER_ACCEPTANCE.value],
            "release": gate_status[ForgeStage.RELEASE.value],
            "production_ready": False,
            "release_authorized": False,
        },
        "limitations": [
            "Static parsing does not prove that generated code builds or runs.",
            "Languages without a configured trusted checker remain inconclusive.",
            "Build, unit, integration, regression and runtime tests were not run.",
            "Security, privacy, legal, accessibility and maintainability reviews were not performed.",
            "Human user acceptance has not been recorded.",
            "No release or deployment has been authorized.",
        ],
    }


def validate_candidate_verification_report(
    files: Mapping[str, str],
    report: Mapping[str, Any],
) -> None:
    """Independently validate candidate/report consistency before vaulting."""
    if not isinstance(files, Mapping) or not files:
        raise ValueError("Candidate files must be a non-empty mapping.")
    if not isinstance(report, Mapping):
        raise TypeError("Verification report must be a mapping.")

    canonical_files: dict[str, str] = {}
    for name, content in files.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Candidate file paths must be non-empty strings.")
        if not isinstance(content, str):
            raise TypeError("Candidate file contents must be strings.")
        canonical_files[name] = content

    expected_digest = _sha256(json.dumps(
        canonical_files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))

    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError("Unsupported candidate verification report schema.")
    if report.get("candidate_files_sha256") != expected_digest:
        raise ValueError("Candidate file-set digest does not match verification report.")

    static = report.get("static_analysis")
    if not isinstance(static, Mapping):
        raise ValueError("Static analysis report is missing or invalid.")
    if static.get("tool") != STATIC_VALIDATOR:
        raise ValueError("Unrecognized static validator.")
    if static.get("tool_version") != STATIC_VALIDATOR_VERSION:
        raise ValueError("Unsupported static validator version.")

    checks = static.get("checks")
    if not isinstance(checks, list):
        raise ValueError("Static analysis checks must be a list.")

    seen: set[str] = set()
    statuses: list[str] = []
    for item in checks:
        if not isinstance(item, Mapping):
            raise ValueError("Static analysis check must be a mapping.")

        name = item.get("file")
        if not isinstance(name, str) or name not in canonical_files:
            raise ValueError("Static analysis references an unknown candidate file.")
        if name in seen:
            raise ValueError("Duplicate static analysis result.")
        if item.get("check") != "static_syntax":
            raise ValueError("Unsupported static analysis check type.")

        status = item.get("status")
        if status not in {"pass", "fail", "inconclusive"}:
            raise ValueError("Static analysis result has an invalid status.")

        expected_file_digest = _sha256(canonical_files[name].encode("utf-8"))
        if item.get("input_sha256") != expected_file_digest:
            raise ValueError("Static analysis input digest does not match candidate file.")
        if not isinstance(item.get("message"), str):
            raise ValueError("Static analysis message is invalid.")

        seen.add(name)
        statuses.append(status)

    expected_static_status = (
        "inconclusive"
        if seen != set(canonical_files)
        else "fail"
        if "fail" in statuses
        else "inconclusive"
        if "inconclusive" in statuses
        else "pass"
    )
    if static.get("status") != expected_static_status:
        raise ValueError("Static analysis summary does not match its check results.")

    expected_gates = {
        stage.value: {
            requirement: "not_run"
            for requirement in sorted(REQUIRED_GATE_EVIDENCE[stage])
        }
        for stage in RELEASE_GATES
    }
    if report.get("gate_evidence") != expected_gates:
        raise ValueError("Candidate contains invalid or unsupported gate evidence.")

    expected_gate_status = {stage: "blocked" for stage in expected_gates}
    if report.get("gate_status") != expected_gate_status:
        raise ValueError("Candidate gate status is inconsistent with its evidence.")

    expected_readiness = {
        "candidate_validation": expected_static_status,
        "self_verification": "blocked",
        "independent_review": "blocked",
        "user_acceptance": "blocked",
        "release": "blocked",
        "production_ready": False,
        "release_authorized": False,
    }
    if report.get("readiness") != expected_readiness:
        raise ValueError("Candidate readiness claims are invalid.")

    limitations = report.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item for item in limitations)
    ):
        raise ValueError("Candidate verification limitations are missing.")
