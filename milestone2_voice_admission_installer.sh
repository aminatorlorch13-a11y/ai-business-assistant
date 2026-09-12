#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$HOME/ai-business-assistant"
cd "$ROOT"

echo "=== AI Business Assistant — Milestone 2 ==="
echo "Authenticated voice-session admission"
echo

HEAD_BEFORE="$(git rev-parse HEAD)"
API_HASH_BEFORE="$(sha256sum app/web/application.py 2>/dev/null || true)"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP=".milestone2_backup_${STAMP}"
mkdir -p "$BACKUP"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "Git HEAD: $HEAD_BEFORE"
echo "Backup:   $BACKUP"
echo

# ---------------------------------------------------------------------------
# Backup only the new milestone targets if they already exist.
# ---------------------------------------------------------------------------

if [[ -e app/assistant/voice_admission.py ]]; then
    cp app/assistant/voice_admission.py "$BACKUP/"
fi

if [[ -e tests/test_voice_session_admission.py ]]; then
    cp tests/test_voice_session_admission.py "$BACKUP/"
fi

# ---------------------------------------------------------------------------
# Voice admission boundary
# ---------------------------------------------------------------------------

cat > "$TMPDIR/voice_admission.py" <<'PY'
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from app.assistant.capability import Capability, CapabilityRequest
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from app.trust.capability_policy import CapabilityPolicy
from app.web.access import (
    BusinessAccess,
    BusinessAccessDenied,
    BusinessAccessService,
)


class VoiceAdmissionDenied(PermissionError):
    """Raised when a caller cannot open an Assistant Core voice session."""


class AuthenticationBoundary(Protocol):
    def validate_session(
        self,
        session_id: str,
    ) -> AuthenticatedPrincipal:
        ...


@dataclass(frozen=True)
class VoiceSessionAdmission:
    """Trusted immutable result handed to the future voice core."""

    tenant: TenantContext
    access: BusinessAccess
    capability: Capability

    def __post_init__(self) -> None:
        if not isinstance(self.tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext.")

        if not isinstance(self.access, BusinessAccess):
            raise TypeError("access must be a BusinessAccess.")

        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if self.tenant.business_id != self.access.business_id:
            raise ValueError(
                "tenant and commercial access must target the same business."
            )

        if not self.access.allowed:
            raise ValueError(
                "Denied commercial access cannot create admission."
            )

        if self.capability is not Capability.VOICE:
            raise ValueError(
                "Voice admission must authorize the VOICE capability."
            )


class VoiceSessionAdmissionService:
    """
    Trusted admission boundary for Assistant Core voice sessions.

    Existing systems remain authoritative:

        AuthenticationService
              ↓
        AuthenticatedPrincipal
              ↓
        TenantContext
              ↓
        BusinessAccessService
              ↓
        CapabilityPolicy
              ↓
        VoiceSessionAdmission
              ↓
        future Assistant Core
    """

    DEFAULT_ALLOWED_ROLES = frozenset(
        {
            UserRole.OWNER,
            UserRole.ADMIN,
        }
    )

    def __init__(
        self,
        authentication: AuthenticationBoundary,
        commercial_access: BusinessAccessService,
        capability_policy_resolver: Callable[[str], CapabilityPolicy],
        *,
        allowed_roles: frozenset[UserRole] | None = None,
    ) -> None:
        if not hasattr(authentication, "validate_session"):
            raise TypeError(
                "authentication must expose validate_session()."
            )

        if not isinstance(
            commercial_access,
            BusinessAccessService,
        ):
            raise TypeError(
                "commercial_access must be a BusinessAccessService."
            )

        if not callable(capability_policy_resolver):
            raise TypeError(
                "capability_policy_resolver must be callable."
            )

        roles = (
            self.DEFAULT_ALLOWED_ROLES
            if allowed_roles is None
            else allowed_roles
        )

        if not isinstance(roles, frozenset):
            raise TypeError(
                "allowed_roles must be a frozenset."
            )

        if not roles:
            raise ValueError(
                "allowed_roles must not be empty."
            )

        if not roles.issubset(set(UserRole)):
            raise ValueError(
                "allowed_roles contains an invalid role."
            )

        self._authentication = authentication
        self._commercial_access = commercial_access
        self._capability_policy_resolver = capability_policy_resolver
        self._allowed_roles = roles

    def admit_session(
        self,
        session_id: str,
        business_id: str,
    ) -> VoiceSessionAdmission:
        """Authenticate and admit a session to Assistant Core."""

        if not isinstance(session_id, str) or not session_id.strip():
            raise VoiceAdmissionDenied(
                "A valid authenticated session is required."
            )

        if not isinstance(business_id, str) or not business_id.strip():
            raise VoiceAdmissionDenied(
                "A valid business context is required."
            )

        try:
            principal = self._authentication.validate_session(
                session_id,
            )
        except Exception as exc:
            # Do not leak whether the session was expired, revoked,
            # nonexistent, or otherwise invalid.
            raise VoiceAdmissionDenied(
                "Authentication is required."
            ) from exc

        return self.admit_principal(
            principal,
            business_id,
        )

    def admit_principal(
        self,
        principal: AuthenticatedPrincipal,
        business_id: str,
    ) -> VoiceSessionAdmission:
        """
        Transport-neutral admission.

        Future WebSocket/realtime transports can authenticate first and then
        call this method without creating another authorization system.
        """

        if not isinstance(
            principal,
            AuthenticatedPrincipal,
        ):
            raise VoiceAdmissionDenied(
                "Invalid authenticated principal."
            )

        if not isinstance(business_id, str) or not business_id.strip():
            raise VoiceAdmissionDenied(
                "A valid business context is required."
            )

        # Identity ↔ tenant invariant.
        try:
            tenant = TenantContext(
                business_id=business_id,
                principal=principal,
            )
        except (TypeError, ValueError) as exc:
            raise VoiceAdmissionDenied(
                "Authentication does not match the business."
            ) from exc

        # Role authorization.
        if principal.role not in self._allowed_roles:
            raise VoiceAdmissionDenied(
                "This account is not permitted to open a voice session."
            )

        # Commercial execution authorization.
        try:
            access = self._commercial_access.require_execution(
                business_id,
            )
        except BusinessAccessDenied as exc:
            raise VoiceAdmissionDenied(
                str(exc),
            ) from exc

        # Capability authorization.
        try:
            policy = self._capability_policy_resolver(
                business_id,
            )
        except Exception as exc:
            raise VoiceAdmissionDenied(
                "Voice capability authorization is unavailable."
            ) from exc

        if not isinstance(policy, CapabilityPolicy):
            raise TypeError(
                "capability_policy_resolver must return CapabilityPolicy."
            )

        request = CapabilityRequest(
            business_id=business_id,
            capability=Capability.VOICE,
            reason="Open authenticated Assistant Core voice session",
        )

        decision = policy.allows(request)

        if not decision:
            raise VoiceAdmissionDenied(
                "Voice capability is not authorized for this business."
            )

        return VoiceSessionAdmission(
            tenant=tenant,
            access=access,
            capability=Capability.VOICE,
        )
PY

cp "$TMPDIR/voice_admission.py" app/assistant/voice_admission.py

# ---------------------------------------------------------------------------
# Milestone 2 tests
# ---------------------------------------------------------------------------

cat > "$TMPDIR/test_voice_session_admission.py" <<'PY'
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
from app.web.access import BusinessAccessService


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

    access = BusinessAccessService(
        database,
        clock=lambda *_: NOW,
    )

    denied = access.resolve(
        "business-1",
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
PY

cp "$TMPDIR/test_voice_session_admission.py" \
   tests/test_voice_session_admission.py

# ---------------------------------------------------------------------------
# Verify public assistant-message endpoint has not changed.
# ---------------------------------------------------------------------------

API_HASH_AFTER="$(sha256sum app/web/application.py 2>/dev/null || true)"

if [[ "$API_HASH_BEFORE" != "$API_HASH_AFTER" ]]; then
    echo "ERROR: app/web/application.py changed unexpectedly."
    exit 21
fi

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

echo
echo "=== COMPILE ==="
python -m compileall -q app tests

echo
echo "=== TARGETED MILESTONE 2 TESTS ==="
python -m pytest -q tests/test_voice_session_admission.py

echo
echo "=== EXISTING VOICE STATE TESTS ==="
python -m pytest -q tests/test_assistant_voice_state.py

echo
echo "=== FULL REGRESSION ==="
python -m pytest -q

echo
echo "=== DIFF CHECK ==="
git diff --check

echo
echo "=== PUBLIC ASSISTANT ENDPOINT INTEGRITY ==="
API_HASH_FINAL="$(sha256sum app/web/application.py 2>/dev/null || true)"

if [[ "$API_HASH_BEFORE" != "$API_HASH_FINAL" ]]; then
    echo "ERROR: public assistant-message application changed."
    exit 22
fi

echo
echo "=============================================="
echo "MILESTONE 2 VERIFIED"
echo "=============================================="
echo
echo "No Git commit was created."
echo "Review the diff before committing."
echo
git status --short
