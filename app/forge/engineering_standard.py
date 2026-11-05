from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ForgeStage(str, Enum):
    DISCOVERY = "discovery"
    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    SELF_VERIFICATION = "self_verification"
    INDEPENDENT_REVIEW = "independent_review"
    USER_ACCEPTANCE = "user_acceptance"
    RELEASE = "release"
    MAINTENANCE = "maintenance"


FORWARD_STAGE_ORDER = (
    ForgeStage.DISCOVERY,
    ForgeStage.REQUIREMENTS,
    ForgeStage.ARCHITECTURE,
    ForgeStage.IMPLEMENTATION,
    ForgeStage.SELF_VERIFICATION,
    ForgeStage.INDEPENDENT_REVIEW,
    ForgeStage.USER_ACCEPTANCE,
    ForgeStage.RELEASE,
    ForgeStage.MAINTENANCE,
)


REQUIRED_GATE_EVIDENCE = MappingProxyType({
    ForgeStage.DISCOVERY: frozenset({
        "user_goal_confirmed",
        "existing_system_inspected",
        "constraints_recorded",
    }),
    ForgeStage.REQUIREMENTS: frozenset({
        "acceptance_criteria",
        "data_classification",
        "jurisdictions_identified",
        "user_approval",
    }),
    ForgeStage.ARCHITECTURE: frozenset({
        "architecture_review",
        "threat_model",
        "data_flow_map",
        "failure_modes",
    }),
    ForgeStage.IMPLEMENTATION: frozenset({
        "code_review",
        "dependency_inventory",
        "license_review",
    }),
    ForgeStage.SELF_VERIFICATION: frozenset({
        "build_verified",
        "unit_tests",
        "integration_tests",
        "regression_tests",
        "runtime_smoke_tests",
    }),
    ForgeStage.INDEPENDENT_REVIEW: frozenset({
        "security_review",
        "privacy_review",
        "legal_risk_review",
        "accessibility_review",
        "maintainability_review",
    }),
    ForgeStage.USER_ACCEPTANCE: frozenset({
        "user_live_test",
        "limitations_disclosed",
        "user_acceptance",
    }),
    ForgeStage.RELEASE: frozenset({
        "release_authorization",
        "backup_and_rollback_verified",
        "deployment_checks",
    }),
    ForgeStage.MAINTENANCE: frozenset({
        "monitoring_plan",
        "ownership_recorded",
        "upgrade_plan",
    }),
})


SECURITY_AND_DUTY_CHECKS = (
    "authentication_and_identity",
    "authorization_and_least_privilege",
    "personal_and_sensitive_data_protection",
    "consent_and_lawful_data_use",
    "jurisdiction_specific_legal_requirements",
    "data_retention_deletion_and_export",
    "data_residency_and_cross_border_transfers",
    "breach_detection_response_and_notification",
    "secrets_and_credential_handling",
    "input_validation_output_encoding_and_injection",
    "dependency_and_software_supply_chain_risk",
    "open_source_and_third_party_licensing",
    "abuse_misuse_fraud_and_rate_limiting",
    "backup_recovery_and_business_continuity",
    "logging_auditability_and_data_minimization",
    "accessibility_and_inclusive_use",
    "operational_cost_and_resource_limits",
    "failure_modes_and_safe_degradation",
)


FRONTEND_DELIVERY_REQUIREMENTS = (
    "responsive_mobile_and_desktop_layout",
    "accessible_semantics_keyboard_and_contrast",
    "real_navigation_and_working_interactions",
    "real_api_and_form_integration_where_required",
    "loading_empty_success_and_error_states",
    "input_validation_and_user_feedback",
    "performance_and_asset_optimization",
    "browser_and_mobile_viewport_verification",
    "no_placeholder_controls_or_fake_functionality",
)


class ForgeReworkReason(str, Enum):
    DEFECT = "defect"
    SECURITY = "security"
    PRIVACY = "privacy"
    LEGAL_OR_REGULATORY = "legal_or_regulatory"
    REGRESSION = "regression"
    COMPATIBILITY = "compatibility"
    OPERATIONAL_RISK = "operational_risk"
    USER_REQUESTED_CHANGE = "user_requested_change"


@dataclass(frozen=True)
class ForgeReworkRequest:
    """A scoped repair record that preserves the accepted project baseline."""

    rework_id: str
    component_id: str
    reason: ForgeReworkReason
    scope: str
    evidence: str
    requested_at: datetime
    user_approved: bool = False

    def __post_init__(self) -> None:
        for name in ("rework_id", "component_id", "scope", "evidence"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
            if len(value) > 2048:
                raise ValueError(f"{name} exceeds the maximum length.")

        if not isinstance(self.reason, ForgeReworkReason):
            raise TypeError("reason must be a ForgeReworkReason.")
        if not isinstance(self.requested_at, datetime):
            raise TypeError("requested_at must be a datetime.")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware.")
        if type(self.user_approved) is not bool:
            raise TypeError("user_approved must be a bool.")
        if (
            self.reason == ForgeReworkReason.USER_REQUESTED_CHANGE
            and not self.user_approved
        ):
            raise ValueError("User-requested changes require explicit user approval.")


def missing_gate_evidence(
    stage: ForgeStage,
    evidence: Mapping[str, bool],
) -> tuple[str, ...]:
    """Return evidence requirements not satisfied for the current stage."""
    if not isinstance(stage, ForgeStage):
        raise TypeError("stage must be a ForgeStage.")
    if not isinstance(evidence, Mapping):
        raise TypeError("evidence must be a mapping.")

    for key, value in evidence.items():
        if not isinstance(key, str):
            raise TypeError("Evidence keys must be strings.")
        if type(value) is not bool:
            raise TypeError("Evidence values must be bools.")

    required = REQUIRED_GATE_EVIDENCE[stage]
    unknown = set(evidence) - required
    if unknown:
        raise ValueError(
            "Unknown evidence keys: " + ", ".join(sorted(unknown))
        )

    return tuple(sorted(
        key for key in required if evidence.get(key) is not True
    ))


def validate_forward_stage_transition(
    current: ForgeStage,
    target: ForgeStage,
    evidence: Mapping[str, bool],
) -> None:
    """Permit only the immediate next stage after the current gate passes."""
    if not isinstance(current, ForgeStage) or not isinstance(target, ForgeStage):
        raise TypeError("current and target must be ForgeStage values.")

    index = FORWARD_STAGE_ORDER.index(current)
    if index == len(FORWARD_STAGE_ORDER) - 1:
        raise ValueError("Maintenance is the final lifecycle stage.")

    expected = FORWARD_STAGE_ORDER[index + 1]
    if target != expected:
        raise ValueError(
            f"Forward progression requires {expected.value}, not {target.value}."
        )

    missing = missing_gate_evidence(current, evidence)
    if missing:
        raise ValueError(
            "Stage gate is not satisfied; missing evidence: "
            + ", ".join(missing)
        )
