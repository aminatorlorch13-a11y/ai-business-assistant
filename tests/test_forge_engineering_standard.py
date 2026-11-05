from datetime import datetime, timezone

import pytest

from app.forge.engineering_standard import (
    FORWARD_STAGE_ORDER,
    FRONTEND_DELIVERY_REQUIREMENTS,
    REQUIRED_GATE_EVIDENCE,
    SECURITY_AND_DUTY_CHECKS,
    ForgeReworkReason,
    ForgeReworkRequest,
    ForgeStage,
    missing_gate_evidence,
    validate_forward_stage_transition,
)

NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)


def complete_evidence(stage):
    return {key: True for key in REQUIRED_GATE_EVIDENCE[stage]}


def test_lifecycle_is_forward_and_has_no_duplicate_stages():
    assert FORWARD_STAGE_ORDER[0] == ForgeStage.DISCOVERY
    assert FORWARD_STAGE_ORDER[-1] == ForgeStage.MAINTENANCE
    assert len(FORWARD_STAGE_ORDER) == len(set(FORWARD_STAGE_ORDER))


def test_stage_cannot_advance_without_all_required_evidence():
    with pytest.raises(ValueError, match="Stage gate is not satisfied"):
        validate_forward_stage_transition(
            ForgeStage.DISCOVERY,
            ForgeStage.REQUIREMENTS,
            {"user_goal_confirmed": True},
        )


def test_stage_advances_when_all_evidence_is_present():
    validate_forward_stage_transition(
        ForgeStage.DISCOVERY,
        ForgeStage.REQUIREMENTS,
        complete_evidence(ForgeStage.DISCOVERY),
    )


@pytest.mark.parametrize(
    "target",
    [ForgeStage.IMPLEMENTATION, ForgeStage.MAINTENANCE],
)
def test_stage_cannot_skip_gates(target):
    with pytest.raises(ValueError, match="Forward progression requires"):
        validate_forward_stage_transition(
            ForgeStage.DISCOVERY,
            target,
            complete_evidence(ForgeStage.DISCOVERY),
        )


def test_stage_cannot_move_backwards():
    with pytest.raises(ValueError, match="Forward progression requires"):
        validate_forward_stage_transition(
            ForgeStage.ARCHITECTURE,
            ForgeStage.REQUIREMENTS,
            complete_evidence(ForgeStage.ARCHITECTURE),
        )


def test_maintenance_is_final():
    with pytest.raises(ValueError, match="final lifecycle stage"):
        validate_forward_stage_transition(
            ForgeStage.MAINTENANCE,
            ForgeStage.MAINTENANCE,
            complete_evidence(ForgeStage.MAINTENANCE),
        )


def test_false_evidence_does_not_pass_gate():
    evidence = complete_evidence(ForgeStage.DISCOVERY)
    evidence["existing_system_inspected"] = False
    assert missing_gate_evidence(ForgeStage.DISCOVERY, evidence) == (
        "existing_system_inspected",
    )


def test_unknown_evidence_key_is_rejected():
    with pytest.raises(ValueError, match="Unknown evidence keys"):
        missing_gate_evidence(
            ForgeStage.DISCOVERY,
            {
                "user_goal_confirmed": True,
                "existing_system_inspected": True,
                "constraints_recorded": True,
                "security_checked": True,
            },
        )


def test_user_requested_rework_requires_approval():
    with pytest.raises(ValueError, match="explicit user approval"):
        ForgeReworkRequest(
            "rw-1",
            "frontend",
            ForgeReworkReason.USER_REQUESTED_CHANGE,
            "Add a new page",
            "User requested a new page",
            NOW,
        )


def test_defect_rework_is_scoped_to_component():
    request = ForgeReworkRequest(
        "rw-2",
        "login-form",
        ForgeReworkReason.DEFECT,
        "Fix incorrect validation",
        "Reproduction steps and failing test",
        NOW,
    )
    assert request.component_id == "login-form"
    assert request.reason == ForgeReworkReason.DEFECT
    assert request.user_approved is False


def test_security_and_frontend_standards_cover_real_risks():
    assert "jurisdiction_specific_legal_requirements" in SECURITY_AND_DUTY_CHECKS
    assert "data_retention_deletion_and_export" in SECURITY_AND_DUTY_CHECKS
    assert "no_placeholder_controls_or_fake_functionality" in FRONTEND_DELIVERY_REQUIREMENTS
    assert "browser_and_mobile_viewport_verification" in FRONTEND_DELIVERY_REQUIREMENTS
