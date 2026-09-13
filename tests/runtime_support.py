from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.persistence.database import SQLiteDatabase
from app.web.access import BusinessAccessService


@dataclass
class RuntimeTestDependencies:
    commercial_access: BusinessAccessService
    tenant: TenantContext
    _temporary_directory: TemporaryDirectory


def make_runtime_dependencies(
    business_id: str,
    *,
    user_id: str = "runtime-test-user",
    role: UserRole = UserRole.OWNER,
) -> RuntimeTestDependencies:
    if not isinstance(business_id, str) or not business_id:
        raise TypeError("business_id must be a non-empty string.")

    temporary_directory = TemporaryDirectory(
        prefix="ai-business-assistant-runtime-test-"
    )

    database = SQLiteDatabase(
        Path(temporary_directory.name) / "runtime.sqlite3"
    )
    database.initialize()

    SQLiteBusinessRepository(database).save(
        Business(
            business_id=business_id,
            name="Runtime Test Business",
            owner_name="Runtime Test Owner",
            assistant_name="Runtime Assistant",
            assistant_voice="male",
        )
    )

    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            business_id=business_id,
            status=CommercialStatus.ACTIVE,
        )
    )

    commercial_access = BusinessAccessService(database)

    principal = AuthenticatedPrincipal(
        user_id=user_id,
        business_id=business_id,
        role=role,
        session_id="runtime-test-session",
    )

    tenant = TenantContext(
        business_id=business_id,
        principal=principal,
    )

    return RuntimeTestDependencies(
        commercial_access=commercial_access,
        tenant=tenant,
        _temporary_directory=temporary_directory,
    )
