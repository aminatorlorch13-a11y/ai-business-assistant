import hashlib
import json

from app.forge.sentinel_guards import GuardInput, GuardVerdict, GUARD_IDS
from app.forge.sentinel_reviewers import (
    build_production_sentinel_reviewers,
    guard1, guard2, guard3, guard4, guard5,
)
from app.forge.verification import build_candidate_verification_report


def make_input(files=None, changes=None):
    files = files or {"src/main.py": "print('hello')"}
    report = build_candidate_verification_report(
        files,
        [{"file": name, "status": "pass", "message": "Static check passed."}
         for name in files],
    )
    candidate = {
        "format": "amination-forge-candidate-v1",
        "business_id": "business-test",
        "project_id": "project-test",
        "job_id": "job-test",
        "files": files,
        "verification": report,
    }
    if changes:
        changes(candidate)
    raw = json.dumps(
        candidate, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode()
    return GuardInput(
        guard_id=GUARD_IDS[0],
        artifact_ref="artifact-test",
        candidate_sha256=hashlib.sha256(raw).hexdigest(),
        candidate_bytes=raw,
    )


def test_all_five_production_reviewers_pass_valid_candidate():
    reviewers = build_production_sentinel_reviewers()
    data = make_input()

    assert len(reviewers) == 5
    assert tuple(item.guard_id for item in reviewers) == GUARD_IDS
    assert len({item.implementation_id for item in reviewers}) == 5
    assert all(item.review(data).verdict is GuardVerdict.PASS for item in reviewers)


def test_guard_two_rejects_path_traversal():
    data = make_input({"../outside.py": "print('unsafe')"})
    assert guard2(data).verdict is GuardVerdict.FAIL


def test_guard_three_rejects_embedded_github_token():
    data = make_input({
        "config.py": 'TOKEN = "ghp_' + ("A" * 30) + '"'
    })
    assert guard3(data).verdict is GuardVerdict.FAIL


def test_guard_four_rejects_tampered_verification_digest():
    def tamper(candidate):
        candidate["verification"]["candidate_files_sha256"] = "0" * 64

    data = make_input(changes=tamper)
    assert guard4(data).verdict is GuardVerdict.FAIL


def test_guard_five_rejects_candidate_claiming_release_authorization():
    def tamper(candidate):
        candidate["verification"]["readiness"]["release_authorized"] = True

    data = make_input(changes=tamper)
    assert guard5(data).verdict is GuardVerdict.FAIL
