from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.assistant.capability import Capability
from app.assistant.voice_admission import (
    VoiceAdmissionDenied,
    VoiceSessionAdmission,
    VoiceSessionAdmissionService,
)
from app.commercial.entitlements import BusinessEntitlements
from app.commercial.state import (
    BusinessCommercialState,
    CommercialStatus,
)
from app.commercial.trial import BusinessTrial
from app.identity.models import (
    AuthenticatedPrincipal,
    UserRole,
)
from app.identity.tenant import TenantContext
from app.models.business import Business
from app.persistence.business_repository import (
    SQLiteBusinessRepository,
)
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.trial_repository import (
    SQLiteTrialRepository,
)
from app.trust.capability_policy import CapabilityPolicy
from app.web.access import (
    BusinessAccess,
    BusinessAccessService,
)


NOW = datetime(
    2026,
    1,
    1,
    12,
    tzinfo=timezone.utc,
)


@dataclass
class FakeAuthentication:
    principal: AuthenticatedPrincipal | None = None
    failure: Exception | None = None

    def validate_session(
        self,
        session_id: str,
    ) -> AuthenticatedPrincipal:
        if not session_id:
            raise RuntimeError("invalid session")

        if self.failure is not None:
            raise self.failure

        if self.principal is None:
            raise RuntimeError("no principal")

        return self.principal


def make_db(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(
        tmp_path / "voice-admission.sqlite3"
    )
    database.initialize()
    return database


def make_business(
    database: SQLiteDatabase,
    business_id: str = "business-1",
) -> Business:
    business = Business(
        business_id,
        "Example Business",
        "Owner",
        "Configured Assistant",
        "male",
    )

    SQLiteBusinessRepository(database).save(
        business,
    )

    return business


def seed_active(
    database: SQLiteDatabase,
    business_id: str,
) -> None:
    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            business_id,
            CommercialStatus.ACTIVE,
        )
    )


def seed_trial(
    database: SQLiteDatabase,
    business_id: str,
    started_at: datetime,
) -> None:
    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            business_id,
            CommercialStatus.TRIAL,
        )
    )

    SQLiteTrialRepository(database).save(
        BusinessTrial(
            business_id,
            started_at,
        )
    )


def make_principal(
    business_id: str = "business-1",
    role: UserRole = UserRole.OWNER,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-1",
        business_id=business_id,
        role=role,
        session_id="session-token",
    )


def make_policy(
    *capabilities: Capability,
) -> CapabilityPolicy:
    entitlements = BusinessEntitlements(
        business_id="business-1",
        capabilities=frozenset(capabilities),
    )

    return CapabilityPolicy.from_entitlements(
        entitlements,
    )


def make_service(
    database: SQLiteDatabase,
    authentication: FakeAuthentication,
    policy: CapabilityPolicy,
) -> VoiceSessionAdmissionService:
    access = BusinessAccessService(
        database,
        clock=lambda *_: NOW,
    )

    def resolve_policy(
        business_id: str,
    ) -> CapabilityPolicy:
        assert business_id == "business-1"
        return policy

    return VoiceSessionAdmissionService(
        authentication=authentication,
        commercial_access=access,
        capability_policy_resolver=resolve_policy,
    )


def test_authenticated_owner_is_admitted(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(),
        ),
        make_policy(Capability.VOICE),
    )

    admission = service.admit_session(
        "session-token",
        "business-1",
    )

    assert isinstance(
        admission,
        VoiceSessionAdmission,
    )
    assert admission.tenant.business_id == "business-1"
    assert admission.tenant.principal.user_id == "user-1"
    assert admission.capability is Capability.VOICE
    assert admission.access.allowed is True


def test_authenticated_admin_is_admitted(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(
                role=UserRole.ADMIN,
            ),
        ),
        make_policy(Capability.VOICE),
    )

    admission = service.admit_session(
        "session-token",
        "business-1",
    )

    assert admission.tenant.principal.role is UserRole.ADMIN


def test_member_is_rejected(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(
                role=UserRole.MEMBER,
            ),
        ),
        make_policy(Capability.VOICE),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
        match="not permitted",
    ):
        service.admit_session(
            "session-token",
            "business-1",
        )


def test_voice_capability_is_required(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(),
        ),
        make_policy(Capability.CONVERSATION),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
        match="Voice capability",
    ):
        service.admit_session(
            "session-token",
            "business-1",
        )


def test_expired_trial_is_rejected(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)

    seed_trial(
        database,
        "business-1",
        NOW - timedelta(days=8),
    )

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(),
        ),
        make_policy(Capability.VOICE),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
        match="expired",
    ):
        service.admit_session(
            "session-token",
            "business-1",
        )


def test_suspended_business_is_rejected(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)

    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            "business-1",
            CommercialStatus.SUSPENDED,
        )
    )

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(),
        ),
        make_policy(Capability.VOICE),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
        match="suspended",
    ):
        service.admit_session(
            "session-token",
            "business-1",
        )


def test_unknown_business_is_rejected(
    tmp_path,
):
    database = make_db(tmp_path)

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(),
        ),
        make_policy(Capability.VOICE),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
    ):
        service.admit_session(
            "session-token",
            "missing-business",
        )


def test_invalid_authentication_is_rejected(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(),
        make_policy(Capability.VOICE),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
        match="Authentication is required",
    ):
        service.admit_session(
            "session-token",
            "business-1",
        )


def test_cross_business_principal_is_rejected(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(
                business_id="business-2",
            ),
        ),
        make_policy(Capability.VOICE),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
        match="does not match",
    ):
        service.admit_session(
            "session-token",
            "business-1",
        )


def test_transport_neutral_principal_path_is_admitted(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(
            principal=make_principal(),
        ),
        make_policy(Capability.VOICE),
    )

    admission = service.admit_principal(
        make_principal(),
        "business-1",
    )

    assert admission.capability is Capability.VOICE


def test_internal_auth_error_is_not_leaked(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)
    seed_active(database, "business-1")

    service = make_service(
        database,
        FakeAuthentication(
            failure=RuntimeError(
                "secret authentication database detail"
            ),
        ),
        make_policy(Capability.VOICE),
    )

    with pytest.raises(
        VoiceAdmissionDenied,
        match="Authentication is required",
    ) as exc_info:
        service.admit_session(
            "session-token",
            "business-1",
        )

    assert "database detail" not in str(exc_info.value)


def test_denied_commercial_access_cannot_become_admission(
    tmp_path,
):
    database = make_db(tmp_path)
    make_business(database)

    denied = BusinessAccess(
        business_id="business-1",
        status=CommercialStatus.EXPIRED,
        allowed=False,
        reason="The business entitlement has expired.",
        trial_ends_at=None,
    )

    tenant = TenantContext(
        "business-1",
        make_principal(),
    )

    with pytest.raises(
        ValueError,
        match="Denied commercial",
    ):
        VoiceSessionAdmission(
            tenant=tenant,
            access=denied,
            capability=Capability.VOICE,
        )
