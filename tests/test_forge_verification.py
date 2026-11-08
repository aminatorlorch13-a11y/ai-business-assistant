import pytest

from app.forge.engineering_standard import ForgeStage, REQUIRED_GATE_EVIDENCE
from app.forge.verification import REPORT_SCHEMA, build_candidate_verification_report


FILES = {"src/main.py": "print('hello')", "README.md": "Candidate"}
CHECKS = [
    {"file": "src/main.py", "passed": True, "message": "Python parsed."},
    {"file": "README.md", "passed": True, "message": "Text accepted."},
]


def test_report_separates_static_analysis_from_engineering_gates():
    report = build_candidate_verification_report(FILES, CHECKS)
    assert report["schema"] == REPORT_SCHEMA
    assert report["static_analysis"]["status"] == "pass"
    evidence = report["gate_evidence"][ForgeStage.SELF_VERIFICATION.value]
    assert set(evidence) == set(REQUIRED_GATE_EVIDENCE[ForgeStage.SELF_VERIFICATION])
    assert set(evidence.values()) == {"not_run"}


def test_static_pass_never_means_production_ready():
    report = build_candidate_verification_report(FILES, CHECKS)
    assert report["readiness"]["candidate_validation"] == "pass"
    assert report["readiness"]["self_verification"] == "blocked"
    assert report["readiness"]["independent_review"] == "blocked"
    assert report["readiness"]["user_acceptance"] == "blocked"
    assert report["readiness"]["release"] == "blocked"
    assert report["readiness"]["production_ready"] is False
    assert report["readiness"]["release_authorized"] is False


def test_failed_static_check_is_reported_as_failure():
    checks = [
        {"file": "src/main.py", "passed": False, "message": "Syntax error."},
        {"file": "README.md", "passed": True, "message": "Text accepted."},
    ]
    report = build_candidate_verification_report(FILES, checks)
    assert report["static_analysis"]["status"] == "fail"
    assert report["readiness"]["production_ready"] is False


def test_report_digest_is_deterministic_and_order_independent():
    first = build_candidate_verification_report(FILES, CHECKS)
    second = build_candidate_verification_report(
        dict(reversed(list(FILES.items()))), list(reversed(CHECKS))
    )
    assert first["candidate_files_sha256"] == second["candidate_files_sha256"]


def test_report_rejects_checks_for_unknown_files():
    with pytest.raises(ValueError, match="unknown candidate file"):
        build_candidate_verification_report(
            FILES, [{"file": "missing.py", "passed": True, "message": "Parsed."}]
        )


def test_report_rejects_duplicate_file_checks():
    with pytest.raises(ValueError, match="Duplicate static check"):
        build_candidate_verification_report(FILES, CHECKS + [CHECKS[0]])


def test_report_rejects_non_boolean_check_outcomes():
    with pytest.raises(TypeError, match="must be a bool"):
        build_candidate_verification_report(
            FILES, [{"file": "src/main.py", "passed": 1, "message": "Parsed."}]
        )


def test_report_rejects_invalid_file_content():
    with pytest.raises(TypeError, match="must contain text"):
        build_candidate_verification_report({"bad.py": b"not text"}, [])
