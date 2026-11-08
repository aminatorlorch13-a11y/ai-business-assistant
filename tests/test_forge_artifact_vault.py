from types import SimpleNamespace

import pytest

from app.forge.artifact_store import ForgeArtifactStore
from app.forge.artifact_vault import ForgeArtifactVault
from app.forge.task_spec import ForgeTaskSpec
from app.forge.worker import ForgeExecutionResult
from app.forge.verification import build_candidate_verification_report


FILES = {"src/main.py": "print('hello')"}
CHECKS = [
    {"file": "src/main.py", "passed": True, "message": "Python parsed."}
]


def make_spec():
    return ForgeTaskSpec(
        business_id="business-test",
        project_id="project-test",
        job_id="job-test",
        instructions="Create a simple candidate.",
        scope=("src/main.py",),
        acceptance_criteria=("Candidate file exists.",),
    )


def make_candidate():
    return {
        "format": "amination-forge-candidate-v1",
        "business_id": "business-test",
        "project_id": "project-test",
        "job_id": "job-test",
        "files": dict(FILES),
        "checks": list(CHECKS),
        "verification": build_candidate_verification_report(FILES, CHECKS),
        "execution_policy": {
            "generated_code_executed": False,
            "live_repository_modified": False,
            "shell_commands_invoked": False,
        },
    }


def make_vault():
    calls = []
    store = object.__new__(ForgeArtifactStore)

    def fake_store(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(artifact_ref="forge-artifact://test")

    store.store = fake_store
    return ForgeArtifactVault(store), calls


def test_vault_stores_candidate_with_valid_verification_report():
    vault, calls = make_vault()
    reference = vault(make_spec(), ForgeExecutionResult(make_candidate()))

    assert reference == "forge-artifact://test"
    assert len(calls) == 1
    assert calls[0]["business_id"] == "business-test"
    assert calls[0]["project_id"] == "project-test"


def test_vault_rejects_candidate_file_tampering_before_storage():
    vault, calls = make_vault()
    candidate = make_candidate()
    candidate["files"]["src/main.py"] = "print('tampered')"

    with pytest.raises(ValueError, match="digest"):
        vault(make_spec(), ForgeExecutionResult(candidate))

    assert calls == []


def test_vault_rejects_false_production_readiness():
    vault, calls = make_vault()
    candidate = make_candidate()
    candidate["verification"]["readiness"]["production_ready"] = True

    with pytest.raises(ValueError, match="readiness"):
        vault(make_spec(), ForgeExecutionResult(candidate))

    assert calls == []


def test_vault_rejects_falsified_static_file_digest():
    vault, calls = make_vault()
    candidate = make_candidate()
    candidate["verification"]["static_analysis"]["checks"][0][
        "input_sha256"
    ] = "0" * 64

    with pytest.raises(ValueError, match="input digest"):
        vault(make_spec(), ForgeExecutionResult(candidate))

    assert calls == []


def test_vault_rejects_missing_verification_report():
    vault, calls = make_vault()
    candidate = make_candidate()
    del candidate["verification"]

    with pytest.raises(TypeError, match="mapping"):
        vault(make_spec(), ForgeExecutionResult(candidate))

    assert calls == []
