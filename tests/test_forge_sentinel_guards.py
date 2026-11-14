import pytest

from app.forge.sentinel_guards import (
    GUARD_IDS,
    AssessmentStatus,
    CandidateChangedError,
    ForgeSentinelAssessmentService,
    GuardDecision,
    GuardReviewer,
    GuardVerdict,
    SentinelConfigurationError,
)


def make_reviewers(verdicts=None, calls=None):
    verdicts = verdicts or {}
    calls = calls if calls is not None else []

    reviewers = []
    for guard_id in GUARD_IDS:
        def review(review_input, current_id=guard_id):
            calls.append(current_id)
            verdict = verdicts.get(current_id, GuardVerdict.PASS)
            if isinstance(verdict, object) and not isinstance(verdict, GuardVerdict):
                return verdict
            return GuardDecision(verdict)

        reviewers.append(
            GuardReviewer(
                guard_id=guard_id,
                implementation_id=f"test-implementation:{guard_id}",
                review=review,
            )
        )
    return reviewers


def test_all_five_guards_run_in_exact_order_and_only_reach_user_acceptance():
    calls = []
    service = ForgeSentinelAssessmentService(make_reviewers(calls=calls))

    result = service.assess(
        artifact_ref="forge-artifact://candidate-1",
        candidate_reader=lambda: b"immutable candidate",
    )

    assert calls == list(GUARD_IDS)
    assert result.status is AssessmentStatus.READY_FOR_USER_ACCEPTANCE
    assert result.all_guards_passed is True
    assert len(result.results) == 5
    assert [item.guard_id for item in result.results] == list(GUARD_IDS)
    assert len({item.candidate_sha256 for item in result.results}) == 1


@pytest.mark.parametrize(
    "verdict",
    [GuardVerdict.FAIL, GuardVerdict.INCONCLUSIVE],
)
def test_non_pass_verdict_halts_immediately(verdict):
    calls = []
    reviewers = make_reviewers(
        verdicts={GUARD_IDS[1]: verdict},
        calls=calls,
    )
    service = ForgeSentinelAssessmentService(reviewers)

    result = service.assess(
        artifact_ref="forge-artifact://candidate-2",
        candidate_reader=lambda: b"candidate",
    )

    assert calls == list(GUARD_IDS[:2])
    assert result.status is AssessmentStatus.BLOCKED
    assert result.blocked_at_guard == GUARD_IDS[1]
    assert len(result.results) == 2
    assert result.all_guards_passed is False


def test_missing_reviewer_blocks_at_its_exact_position():
    calls = []
    reviewers = make_reviewers(calls=calls)
    reviewers[2] = None

    service = ForgeSentinelAssessmentService(reviewers)
    result = service.assess(
        artifact_ref="forge-artifact://candidate-3",
        candidate_reader=lambda: b"candidate",
    )

    assert calls == list(GUARD_IDS[:2])
    assert result.status is AssessmentStatus.BLOCKED
    assert result.blocked_at_guard == GUARD_IDS[2]
    assert result.results[-1].verdict is GuardVerdict.INCONCLUSIVE
    assert result.results[-1].implementation_id is None


def test_malformed_reviewer_result_becomes_inconclusive_and_blocks():
    calls = []
    reviewers = make_reviewers(calls=calls)

    reviewers[0] = GuardReviewer(
        guard_id=GUARD_IDS[0],
        implementation_id="malformed-test",
        review=lambda _: {"verdict": "PASS"},
    )

    service = ForgeSentinelAssessmentService(reviewers)
    result = service.assess(
        artifact_ref="forge-artifact://candidate-4",
        candidate_reader=lambda: b"candidate",
    )

    assert calls == []
    assert result.status is AssessmentStatus.BLOCKED
    assert result.blocked_at_guard == GUARD_IDS[0]
    assert result.results[0].verdict is GuardVerdict.INCONCLUSIVE


def test_reviewer_exception_becomes_inconclusive_and_blocks():
    reviewers = make_reviewers()

    def crash(_):
        raise RuntimeError("private internal detail")

    reviewers[0] = GuardReviewer(
        guard_id=GUARD_IDS[0],
        implementation_id="crashing-test",
        review=crash,
    )

    service = ForgeSentinelAssessmentService(reviewers)
    result = service.assess(
        artifact_ref="forge-artifact://candidate-5",
        candidate_reader=lambda: b"candidate",
    )

    assert result.status is AssessmentStatus.BLOCKED
    assert result.blocked_at_guard == GUARD_IDS[0]
    assert result.results[0].verdict is GuardVerdict.INCONCLUSIVE
    assert "private internal detail" not in str(result.results[0].findings)


def test_candidate_change_during_review_invalidates_cycle():
    candidate = bytearray(b"original candidate")
    reviewers = make_reviewers()

    def mutate_candidate(_):
        candidate[:] = b"modified candidate"
        return GuardDecision(GuardVerdict.PASS)

    reviewers[0] = GuardReviewer(
        guard_id=GUARD_IDS[0],
        implementation_id="mutating-test",
        review=mutate_candidate,
    )

    service = ForgeSentinelAssessmentService(reviewers)

    with pytest.raises(CandidateChangedError):
        service.assess(
            artifact_ref="forge-artifact://candidate-6",
            candidate_reader=lambda: bytes(candidate),
        )


def test_wrong_reviewer_order_is_rejected_during_configuration():
    reviewers = make_reviewers()
    reviewers[0], reviewers[1] = reviewers[1], reviewers[0]

    with pytest.raises(SentinelConfigurationError):
        ForgeSentinelAssessmentService(reviewers)


def test_wrong_number_of_reviewer_slots_is_rejected():
    with pytest.raises(SentinelConfigurationError):
        ForgeSentinelAssessmentService([None] * 4)


def test_candidate_reader_must_return_nonempty_bytes():
    service = ForgeSentinelAssessmentService(make_reviewers())

    with pytest.raises(Exception):
        service.assess(
            artifact_ref="forge-artifact://candidate-7",
            candidate_reader=lambda: "",
        )
