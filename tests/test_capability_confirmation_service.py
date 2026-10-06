from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.assistant.capability import Capability
from app.assistant.capability_confirmation_service import (
    CAPABILITY_CONFIRMATION_TTL,
    CapabilityConfirmationService,
)
from app.assistant.execution import CapabilityExecutionRequest
from app.auth.session_security import hash_session_id
from app.identity.models import AuthenticatedPrincipal, SessionScope, UserRole
from app.identity.tenant import TenantContext
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.database import SQLiteDatabase


def _tenant(
    *,
    business_id: str = "business-1",
    user_id: str = "user-1",
    role: UserRole = UserRole.OWNER,
    session_id: str = "session-1",
) -> TenantContext:
    principal = AuthenticatedPrincipal(
        user_id=user_id,
        business_id=business_id,
        role=role,
        session_id=session_id,
        scope=SessionScope.BUSINESS,
    )
    return TenantContext(
        business_id=business_id,
        principal=principal,
    )


def _request(
    *,
    business_id: str = "business-1",
    channel: str | None = "web",
    integration: str | None = "internal",
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability=Capability.MEMORY,
        operation="save",
        business_id=business_id,
        arguments={"content": "confirmed content"},
        reason="User explicitly requested the memory to be saved.",
        channel=channel,
        integration=integration,
    )


def _seed_business_and_user(database: SQLiteDatabase) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id,
                name,
                owner_name,
                assistant_name,
                assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "business-1",
                "Confirmation Service Test Business",
                "Owner",
                "Assistant",
                "calm",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(
                user_id,
                display_name,
                email
            )
            VALUES (?, ?, ?)
            """,
            (
                "user-1",
                "Test User",
                "user@example.com",
            ),
        )


def _service(tmp_path, *, now: datetime | None = None):
    database = SQLiteDatabase(tmp_path / "service.db")
    database.initialize()
    _seed_business_and_user(database)
    repository = SQLiteCapabilityConfirmationRepository(database)
    clock_now = now or datetime(2026, 9, 20, 15, 30, tzinfo=timezone.utc)

    service = CapabilityConfirmationService(
        repository,
        clock=lambda: clock_now,
    )
    return database, repository, service, clock_now


def test_create_persists_exact_trusted_binding_and_request(tmp_path):
    database, repository, service, now = _service(tmp_path)
    tenant = _tenant(
        business_id="business-1",
        user_id="user-1",
        role=UserRole.ADMIN,
        session_id="opaque-session-secret",
    )
    request = _request(
        business_id="business-1",
        channel="web",
        integration="internal",
    )

    confirmation = service.create(request, tenant=tenant)
    stored = repository.get(confirmation.confirmation_id)

    assert stored is not None
    assert stored.confirmation_id == confirmation.confirmation_id
    assert stored.session_id_hash == hash_session_id("opaque-session-secret")
    assert stored.session_id_hash != "opaque-session-secret"
    assert stored.user_id == "user-1"
    assert stored.business_id == "business-1"
    assert stored.role is UserRole.ADMIN
    assert stored.request == request
    assert stored.created_at == now
    assert stored.expires_at == now + CAPABILITY_CONFIRMATION_TTL
    assert stored.consumed_at is None
    assert stored.revoked_at is None



def test_create_rejects_request_for_different_business(tmp_path):
    database, _, service, _ = _service(tmp_path)
    tenant = _tenant(business_id="business-1")
    request = _request(business_id="business-2")

    with pytest.raises(PermissionError):
        service.create(request, tenant=tenant)



def test_create_rejects_non_tenant_principal_at_service_boundary(tmp_path):
    database = SQLiteDatabase(tmp_path / "platform.db")
    database.initialize()
    _seed_business_and_user(database)

    repository = SQLiteCapabilityConfirmationRepository(database)
    service = CapabilityConfirmationService(
        repository,
        clock=lambda: datetime(
            2026,
            9,
            20,
            15,
            30,
            tzinfo=timezone.utc,
        ),
    )

    principal = AuthenticatedPrincipal(
        user_id="platform-user",
        business_id=None,
        role=None,
        session_id="platform-session",
        scope=SessionScope.PLATFORM,
    )

    with pytest.raises(TypeError):
        service.create(
            _request(),
            tenant=principal,  # type: ignore[arg-type]
        )

def test_create_generates_distinct_confirmation_ids(tmp_path):
    database, _, service, _ = _service(tmp_path)
    tenant = _tenant()
    request = _request()

    first = service.create(request, tenant=tenant)
    second = service.create(request, tenant=tenant)

    assert first.confirmation_id
    assert second.confirmation_id
    assert first.confirmation_id != second.confirmation_id



def test_create_replaces_previous_pending_confirmation_for_same_binding(tmp_path):
    database, repository, service, _ = _service(tmp_path)
    tenant = _tenant(session_id="same-session")

    first = service.create(_request(), tenant=tenant)
    second = service.create(_request(), tenant=tenant)

    first_stored = repository.get(first.confirmation_id)
    second_stored = repository.get(second.confirmation_id)

    assert first_stored is not None
    assert second_stored is not None
    assert first_stored.revoked_at is not None
    assert second_stored.revoked_at is None
    assert second_stored.consumed_at is None



def test_create_does_not_replace_confirmation_for_different_channel(tmp_path):
    database, repository, service, _ = _service(tmp_path)
    tenant = _tenant()

    first = service.create(
        _request(channel="web", integration="internal"),
        tenant=tenant,
    )
    second = service.create(
        _request(channel="whatsapp", integration="internal"),
        tenant=tenant,
    )

    assert repository.get(first.confirmation_id).revoked_at is None
    assert repository.get(second.confirmation_id).revoked_at is None



def test_create_does_not_replace_confirmation_for_different_integration(tmp_path):
    database, repository, service, _ = _service(tmp_path)
    tenant = _tenant()

    first = service.create(
        _request(channel="web", integration="internal"),
        tenant=tenant,
    )
    second = service.create(
        _request(channel="web", integration="external"),
        tenant=tenant,
    )

    assert repository.get(first.confirmation_id).revoked_at is None
    assert repository.get(second.confirmation_id).revoked_at is None



def test_consume_requires_exact_session_user_business_role_and_channel_binding(
    tmp_path,
):
    database, _, service, now = _service(tmp_path)

    tenant = _tenant(
        business_id="business-1",
        user_id="user-1",
        role=UserRole.OWNER,
        session_id="session-good",
    )
    confirmation = service.create(
        _request(channel="web", integration="internal"),
        tenant=tenant,
    )

    wrong_session = _tenant(
        business_id="business-1",
        user_id="user-1",
        role=UserRole.OWNER,
        session_id="session-wrong",
    )
    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=wrong_session,
            channel="web",
            integration="internal",
        )
        is None
    )

    wrong_user = _tenant(
        business_id="business-1",
        user_id="user-2",
        role=UserRole.OWNER,
        session_id="session-good",
    )
    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=wrong_user,
            channel="web",
            integration="internal",
        )
        is None
    )

    wrong_business = _tenant(
        business_id="business-2",
        user_id="user-1",
        role=UserRole.OWNER,
        session_id="session-good",
    )
    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=wrong_business,
            channel="web",
            integration="internal",
        )
        is None
    )

    wrong_role = _tenant(
        business_id="business-1",
        user_id="user-1",
        role=UserRole.ADMIN,
        session_id="session-good",
    )
    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=wrong_role,
            channel="web",
            integration="internal",
        )
        is None
    )

    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="whatsapp",
            integration="internal",
        )
        is None
    )

    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="web",
            integration="external",
        )
        is None
    )

    consumed = service.consume(
        confirmation.confirmation_id,
        tenant=tenant,
        channel="web",
        integration="internal",
    )

    assert consumed is not None
    assert consumed.request == _request(
        channel="web",
        integration="internal",
    )
    assert consumed.consumed_at is not None
    assert consumed.revoked_at is None
    assert consumed.is_pending(now) is False



def test_consume_is_single_use(tmp_path):
    database, _, service, _ = _service(tmp_path)
    tenant = _tenant()
    confirmation = service.create(_request(), tenant=tenant)

    first = service.consume(
        confirmation.confirmation_id,
        tenant=tenant,
        channel="web",
        integration="internal",
    )
    second = service.consume(
        confirmation.confirmation_id,
        tenant=tenant,
        channel="web",
        integration="internal",
    )

    assert first is not None
    assert second is None



def test_consume_rejects_expired_confirmation(tmp_path):
    database, _, _, created_at = _service(tmp_path)

    current = [created_at]
    repository = SQLiteCapabilityConfirmationRepository(database)
    service = CapabilityConfirmationService(
        repository,
        clock=lambda: current[0],
    )
    tenant = _tenant()

    confirmation = service.create(_request(), tenant=tenant)
    current[0] = confirmation.expires_at

    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="web",
            integration="internal",
        )
        is None
    )



def test_revoke_requires_exact_binding_and_is_single_use(tmp_path):
    database, _, service, _ = _service(tmp_path)
    tenant = _tenant()
    confirmation = service.create(_request(), tenant=tenant)

    assert (
        service.revoke(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="whatsapp",
            integration="internal",
        )
        is False
    )

    assert (
        service.revoke(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="web",
            integration="internal",
        )
        is True
    )

    assert (
        service.revoke(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="web",
            integration="internal",
        )
        is False
    )



def test_revoked_confirmation_cannot_be_consumed(tmp_path):
    database, _, service, _ = _service(tmp_path)
    tenant = _tenant()
    confirmation = service.create(_request(), tenant=tenant)

    assert (
        service.revoke(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="web",
            integration="internal",
        )
        is True
    )

    assert (
        service.consume(
            confirmation.confirmation_id,
            tenant=tenant,
            channel="web",
            integration="internal",
        )
        is None
    )



@pytest.mark.parametrize(
    "bad_clock",
    [
        lambda: datetime(2026, 9, 20, 15, 30),
        lambda: "not-a-datetime",
    ],
)
def test_service_rejects_invalid_clock(bad_clock, tmp_path):
    database = SQLiteDatabase(tmp_path / "clock.db")
    database.initialize()
    repository = SQLiteCapabilityConfirmationRepository(database)
    service = CapabilityConfirmationService(
        repository,
        clock=bad_clock,
    )

    with pytest.raises((TypeError, ValueError)):
        service.create(_request(), tenant=_tenant())



@pytest.mark.parametrize(
    "ttl",
    [
        timedelta(0),
        timedelta(seconds=-1),
    ],
)
def test_service_rejects_non_positive_ttl(ttl, tmp_path):
    database = SQLiteDatabase(tmp_path / "ttl.db")
    database.initialize()
    repository = SQLiteCapabilityConfirmationRepository(database)

    with pytest.raises(ValueError):
        CapabilityConfirmationService(
            repository,
            confirmation_ttl=ttl,
        )



def test_service_rejects_non_timedelta_ttl(tmp_path):
    database = SQLiteDatabase(tmp_path / "ttl-type.db")
    database.initialize()
    repository = SQLiteCapabilityConfirmationRepository(database)

    with pytest.raises(TypeError):
        CapabilityConfirmationService(
            repository,
            confirmation_ttl=5,  # type: ignore[arg-type]
        )



def test_service_rejects_invalid_request_and_tenant_types(tmp_path):
    database = SQLiteDatabase(tmp_path / "types.db")
    database.initialize()
    repository = SQLiteCapabilityConfirmationRepository(database)
    service = CapabilityConfirmationService(repository)

    with pytest.raises(TypeError):
        service.create("not-a-request", tenant=_tenant())  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        service.create(_request(), tenant="not-a-tenant")  # type: ignore[arg-type]



def test_service_consume_and_revoke_reject_invalid_tenant_type(tmp_path):
    database = SQLiteDatabase(tmp_path / "invalid-tenant.db")
    database.initialize()
    repository = SQLiteCapabilityConfirmationRepository(database)
    service = CapabilityConfirmationService(repository)

    with pytest.raises(TypeError):
        service.consume(
            "confirmation-id",
            tenant="not-a-tenant",  # type: ignore[arg-type]
            channel="web",
            integration="internal",
        )

    with pytest.raises(TypeError):
        service.revoke(
            "confirmation-id",
            tenant="not-a-tenant",  # type: ignore[arg-type]
            channel="web",
            integration="internal",
        )
