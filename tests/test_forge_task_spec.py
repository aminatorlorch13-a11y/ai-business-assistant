import json

import pytest

from app.forge.task_spec import ForgeTaskSpec


def make_spec(**overrides):
    values = {
        "business_id": "business-1",
        "project_id": "project-1",
        "job_id": "job-1",
        "instructions": "Review the authentication implementation.",
        "scope": ("app/auth", "tests/auth"),
        "acceptance_criteria": ("All relevant tests pass.",),
    }
    values.update(overrides)
    return ForgeTaskSpec(**values)


def test_task_spec_round_trips_and_preserves_hash():
    original = make_spec()
    restored = ForgeTaskSpec.from_json(original.to_json())

    assert restored == original
    assert restored.sha256 == original.sha256


def test_hash_changes_when_approved_instructions_change():
    original = make_spec()
    changed = make_spec(instructions="Review the payment implementation.")

    assert original.sha256 != changed.sha256


def test_task_spec_rejects_empty_instructions():
    with pytest.raises(ValueError, match="must not be empty"):
        make_spec(instructions="  ")


def test_task_spec_requires_acceptance_criteria():
    with pytest.raises(ValueError, match="At least one"):
        make_spec(acceptance_criteria=())


def test_task_spec_rejects_non_tuple_scope():
    with pytest.raises(TypeError, match="scope must be a tuple"):
        make_spec(scope=["app/auth"])


def test_task_spec_rejects_oversized_instructions():
    with pytest.raises(ValueError, match="maximum length"):
        make_spec(instructions="x" * 20_001)


def test_task_spec_rejects_malformed_json():
    with pytest.raises(ValueError, match="Stored Forge task"):
        ForgeTaskSpec.from_json("{invalid")


def test_task_spec_rejects_non_object_json():
    with pytest.raises(ValueError, match="JSON object"):
        ForgeTaskSpec.from_json(json.dumps([]))
