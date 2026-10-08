from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.ai_result import AIResult
from app.assistant.capability import Capability
from app.assistant.capability_confirmation_service import (
    CapabilityConfirmationService,
)
from app.assistant.capability_preparation import CapabilityExecutionPreparer
from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.commercial.access import BusinessAccessService
from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from app.models.business import Business
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.database import SQLiteDatabase
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_operation_policy import CapabilityOperationPolicy


BUSINESS_ID = "business-001"


def make_business() -> Business:
    return Business(
        business_id=BUSINESS_ID,
        name="Business One",
        owner_name="Owner One",
        assistant_name="Business Assistant",
        assistant_voice="female",
    )


def make_tenant() -> TenantContext:
    principal = AuthenticatedPrincipal(
        user_id="user-001",
        business_id=BUSINESS_ID,
        role=UserRole.OWNER,
        session_id="session-001",
    )
    return TenantContext(
        business_id=BUSINESS_ID,
        principal=principal,
    )


def make_calendar_request() -> AICapabilityRequest:
    return AICapabilityRequest(
        capability=Capability.CALENDAR,
        operation="create_event",
        arguments={
            "title": "Requested appointment",
            "attendee": "owner@example.com",
        },
        reason="Create the appointment requested by the business owner.",
        reversible=True,
    )


def make_structured_stack(tmp_path: Path):
    processor = Mock(spec=StructuredAssistantProcessor)
    executor = Mock(spec=CapabilityExecutor)

    database = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    database.initialize()

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
                BUSINESS_ID,
                "Business One",
                "Owner One",
                "Business Assistant",
                "female",
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
                "user-001",
                "Owner One",
                "owner@example.com",
            ),
        )

    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            BUSINESS_ID,
            CommercialStatus.ACTIVE,
        )
    )

    confirmation_repository = SQLiteCapabilityConfirmationRepository(
        database
    )
    confirmation_service = CapabilityConfirmationService(
        confirmation_repository,
        clock=lambda: datetime(
            2026,
            9,
            20,
            15,
            30,
            tzinfo=timezone.utc,
        ),
    )
    commercial_access = BusinessAccessService(
        database,
        clock=lambda: datetime(
            2026,
            9,
            20,
            15,
            30,
            tzinfo=timezone.utc,
        ),
    )

    # The business is explicitly entitled to MEMORY only.
    # Calendar is deliberately not granted or registered in production.
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO business_capability_entitlements(
                business_id,
                configured_at
            )
            VALUES (?, ?)
            """,
            (
                BUSINESS_ID,
                "2026-09-20T15:30:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO business_capability_grants(
                business_id,
                capability
            )
            VALUES (?, ?)
            """,
            (
                BUSINESS_ID,
                "memory",
            ),
        )

    operation_policy = CapabilityOperationPolicy(
        confirmation_by_operation={
            Capability.MEMORY: {
                "save": False,
                "get": False,
                "list": False,
                "delete": True,
            }
        }
    )

    return (
        processor,
        executor,
        operation_policy,
        confirmation_service,
        commercial_access,
        database,
    )


def make_orchestrator(
    processor,
    executor,
    operation_policy,
    confirmation_service,
    commercial_access,
) -> AssistantOrchestrator:
    return AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
        capability_operation_policy=operation_policy,
        capability_preparer=CapabilityExecutionPreparer(),
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )


def test_structured_appointment_proposal_cannot_reach_legacy_execution(
    tmp_path: Path,
):
    (
        processor,
        executor,
        operation_policy,
        confirmation_service,
        commercial_access,
        _database,
    ) = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(make_calendar_request(),),
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        operation_policy,
        confirmation_service,
        commercial_access,
    )

    message = AssistantMessage(
        business_id=BUSINESS_ID,
        content="Please create an appointment.",
    )

    tenant = make_tenant()

    with pytest.raises(
        LookupError,
        match=r"No policy registered for capability 'calendar'\.",
    ):
        orchestrator.handle(
            message,
            tenant=tenant,
            channel="web",
        )

    executor.execute.assert_not_called()


def test_structured_appointment_proposal_cannot_bypass_closed_world_registry(
    tmp_path: Path,
):
    (
        processor,
        _mock_executor,
        operation_policy,
        confirmation_service,
        commercial_access,
        database,
    ) = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(make_calendar_request(),),
    )

    # Use the real production capability stack. Calendar is intentionally
    # absent from both explicit entitlements and the concrete router.
    from app.assistant.capability_composition import (
        build_production_capability_composition,
    )

    composition = build_production_capability_composition(
        database=database,
    )

    real_executor = composition.executor_for_business(BUSINESS_ID)

    orchestrator = make_orchestrator(
        processor,
        real_executor,
        operation_policy,
        confirmation_service,
        commercial_access,
    )

    message = AssistantMessage(
        business_id=BUSINESS_ID,
        content="Please create an appointment.",
    )

    tenant = make_tenant()

    with pytest.raises(
        LookupError,
        match=r"No policy registered for capability 'calendar'\.",
    ):
        orchestrator.handle(
            message,
            tenant=tenant,
            channel="web",
        )

    assert composition.router.supports(Capability.CALENDAR) is False
    assert composition.router.supports_operation(
        Capability.CALENDAR,
        "create_event",
    ) is False
