from __future__ import annotations

from app.assistant.ai_result import AIResult
from app.assistant.capability_confirmation_service import (
    CapabilityConfirmationService,
)
from app.assistant.capability_preparation import CapabilityExecutionPreparer
from app.assistant.conversation import ConversationHistory
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from app.assistant.message import AssistantMessage
from app.assistant.response import AssistantResponse
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.automation.context import AutomationContext
from app.commercial.access import BusinessAccessService
from app.identity.tenant import TenantContext
from app.models.business import Business
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_operation_policy import CapabilityOperationPolicy


class AssistantOrchestrator:
    """
    Canonical application orchestration boundary.

    Structured orchestration boundary:

        StructuredAssistantProcessor -> AIResult
            -> CapabilityExecutionPreparer
            -> trusted confirmation policy
            -> CapabilityExecutor

    AI output never authorizes, confirms, or executes a capability.
    """

    def __init__(
        self,
        business: Business,
        processor: StructuredAssistantProcessor,
        executor: CapabilityExecutor,
        *,
        capability_operation_policy: CapabilityOperationPolicy | None = None,
        capability_preparer: CapabilityExecutionPreparer | None = None,
        confirmation_service: CapabilityConfirmationService | None = None,
        commercial_access: BusinessAccessService | None = None,
    ) -> None:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")

        if not isinstance(processor, StructuredAssistantProcessor):
            raise TypeError(
                "processor must be a StructuredAssistantProcessor."
            )

        if not isinstance(executor, CapabilityExecutor):
            raise TypeError(
                "executor must be a CapabilityExecutor."
            )

        if not isinstance(
            capability_operation_policy,
            CapabilityOperationPolicy,
        ):
            raise TypeError(
                "capability_operation_policy is required."
            )

        if capability_preparer is not None and not isinstance(
            capability_preparer,
            CapabilityExecutionPreparer,
        ):
            raise TypeError(
                "capability_preparer must be a "
                "CapabilityExecutionPreparer or None."
            )

        if not isinstance(
            confirmation_service,
            CapabilityConfirmationService,
        ):
            raise TypeError(
                "confirmation_service is required."
            )

        if not isinstance(
            commercial_access,
            BusinessAccessService,
        ):
            raise TypeError(
                "commercial_access is required."
            )

        self._business = business
        self._processor = processor
        self._executor = executor
        self._capability_operation_policy = capability_operation_policy
        self._capability_preparer = (
            capability_preparer or CapabilityExecutionPreparer()
        )
        self._confirmation_service = confirmation_service
        self._commercial_access = commercial_access

    def handle(
        self,
        message: AssistantMessage,
        confirmed: bool = False,
        automation_context: AutomationContext | None = None,
        tenant: TenantContext | None = None,
        conversation_history: ConversationHistory | None = None,
        *,
        channel: str | None = None,
        confirmation_id: str | None = None,
        integration: str | None = None,
    ) -> AssistantResponse:
        if not isinstance(message, AssistantMessage):
            raise TypeError("message must be an AssistantMessage.")

        if message.business_id != self._business.business_id:
            raise ValueError(
                "Message does not belong to this business."
            )

        if not isinstance(confirmed, bool):
            raise TypeError("confirmed must be a boolean.")

        if automation_context is not None and not isinstance(
            automation_context,
            AutomationContext,
        ):
            raise TypeError(
                "automation_context must be an AutomationContext or None."
            )

        if (
            automation_context is not None
            and automation_context.business_id != message.business_id
        ):
            raise ValueError(
                "Automation context does not belong to this message business."
            )

        if conversation_history is not None and not isinstance(
            conversation_history,
            ConversationHistory,
        ):
            raise TypeError(
                "conversation_history must be a ConversationHistory or None."
            )

        if (
            conversation_history is not None
            and conversation_history.business_id != message.business_id
        ):
            raise ValueError(
                "Conversation history does not belong to this message business."
            )

        if tenant is not None and not isinstance(tenant, TenantContext):
            raise TypeError(
                "tenant must be a TenantContext or None."
            )

        if channel is not None and (
            not isinstance(channel, str) or not channel.strip()
        ):
            raise ValueError(
                "channel must be a non-empty string when provided."
            )

        if integration is not None and (
            not isinstance(integration, str) or not integration.strip()
        ):
            raise ValueError(
                "integration must be a non-empty string when provided."
            )

        if (
            tenant is not None
            and tenant.business_id != message.business_id
        ):
            raise ValueError(
                "Execution tenant does not belong to this message business."
            )

        return self._handle_structured(
            message,
            confirmed=confirmed,
            automation_context=automation_context,
            tenant=tenant,
            conversation_history=conversation_history,
            channel=channel,
            integration=integration,
            confirmation_id=confirmation_id,
        )

    def _handle_structured(
        self,
        message: AssistantMessage,
        *,
        confirmed: bool,
        automation_context: AutomationContext | None,
        tenant: TenantContext | None,
        conversation_history: ConversationHistory | None,
        channel: str | None,
        integration: str | None,
        confirmation_id: str | None,
    ) -> AssistantResponse:
        assert isinstance(
            self._processor,
            StructuredAssistantProcessor,
        )
        assert isinstance(
            self._executor,
            CapabilityExecutor,
        )
        assert self._capability_operation_policy is not None

        if confirmed:
            raise ValueError(
                "Structured capability confirmation requires a confirmation_id."
            )

        if confirmation_id is not None:
            return self._execute_confirmation(
                confirmation_id,
                tenant=tenant,
                channel=channel,
                integration=integration,
            )

        result = self._processor.process(
            message,
            automation_context=automation_context,
            conversation_history=conversation_history,
        )

        if not isinstance(result, AIResult):
            raise TypeError(
                "Structured processor returned an invalid AIResult."
            )

        if not result.capability_requests:
            return AssistantResponse(
                business_id=self._business.business_id,
                assistant_name=self._business.assistant_name,
                message=result.response or "",
            )

        responses: list[str] = []

        for ai_request in result.capability_requests:
            execution_request = self._capability_preparer.prepare(
                ai_request,
                business_id=self._business.business_id,
                channel=channel,
                integration=integration,
            )

            is_memory_save = (
                execution_request.capability.value == "memory"
                and execution_request.operation == "save"
            )

            if is_memory_save:
                proposed_content = execution_request.arguments.get("content")
                if not isinstance(proposed_content, str) or not proposed_content.strip():
                    responses.append(
                        "I couldn't prepare a memory because its content is missing or invalid."
                    )
                    continue

                if not self._user_explicitly_requested_memory_save(message.content):
                    responses.append(
                        "I won't save a memory based only on an AI suggestion. "
                        "If you want this saved, explicitly ask me to remember it. Proposed memory: "
                        f"{proposed_content!r}"
                    )
                    continue

            requires_confirmation = (
                self._capability_operation_policy.requires_confirmation(
                    execution_request.capability,
                    execution_request.operation,
                )
                or is_memory_save
            )
            if requires_confirmation:
                if tenant is None:
                    raise PermissionError('Authenticated tenant context is required for capability confirmation.')
                assert self._commercial_access is not None
                assert self._confirmation_service is not None

                self._commercial_access.require_execution(
                    self._business.business_id
                )

                # Fail closed before issuing a confirmation.
                # Execution repeats these checks when approval is used.
                self._executor.authorize(
                    execution_request,
                    tenant=tenant,
                )

                confirmation = self._confirmation_service.create(
                    execution_request,
                    tenant=tenant,
                )

                responses.append(
                    self._confirmation_message(
                        execution_request,
                        confirmation.confirmation_id,
                    )
                )
                continue

            execution_result = self._execute_capability(
                execution_request,
                tenant,
            )

            responses.append(
                self._result_message(execution_result)
            )

        if result.response:
            responses.insert(0, result.response)

        return AssistantResponse(
            business_id=self._business.business_id,
            assistant_name=self._business.assistant_name,
            message="\n".join(responses),
        )

    def _execute_confirmation(
        self,
        confirmation_id: str,
        *,
        tenant: TenantContext | None,
        channel: str | None,
        integration: str | None,
    ) -> AssistantResponse:
        if tenant is None:
            raise PermissionError(
                "Authenticated tenant context is required for capability confirmation."
            )

        if not isinstance(confirmation_id, str) or not confirmation_id.strip():
            raise ValueError("confirmation_id must be a non-empty string.")

        assert self._confirmation_service is not None
        assert self._commercial_access is not None

        confirmation = self._confirmation_service.consume(
            confirmation_id,
            tenant=tenant,
            channel=channel,
            integration=integration,
        )
        if confirmation is None:
            raise PermissionError('Capability confirmation is invalid, expired, or does not match this session, channel, or integration.')
        self._commercial_access.require_execution(self._business.business_id)
        result = self._execute_capability(confirmation.request, tenant)

        return AssistantResponse(
            business_id=self._business.business_id,
            assistant_name=self._business.assistant_name,
            message=self._result_message(result),
        )

    @staticmethod
    def _user_explicitly_requested_memory_save(content: str) -> bool:
        if not isinstance(content, str):
            return False

        text = " ".join(
            content.casefold().replace("’", "'").split()
        )

        # Questions are not consent to persist information.
        if text.endswith("?"):
            return False

        negative_phrases = (
            "don't want you to remember",
            "do not want you to remember",
            "don't want this stored",
            "do not want this stored",
            "don't consent to saving",
            "do not consent to saving",
            "don't consent to save",
            "do not consent to save",
            "don't want you to save",
            "do not want you to save",
            "don't want you to store",
            "do not want you to store",
            "don't remember",
            "do not remember",
            "never remember",
            "don't save",
            "do not save",
            "never save",
            "don't store",
            "do not store",
            "never store",
            "not asking you to remember",
            "not asking you to save",
            "not asking you to store",
            "didn't ask you to remember",
            "did not ask you to remember",
        )
        if any(phrase in text for phrase in negative_phrases):
            return False

        # Accept clear instructions only at the beginning of the message.
        explicit_prefixes = (
            "remember that ",
            "remember this",
            "please remember ",
            "save this to memory",
            "save this in memory",
            "store this in memory",
            "please save this",
            "please store this",
            "keep a note that ",
            "don't forget that ",
            "do not forget that ",
        )
        return text.startswith(explicit_prefixes)

    def _execute_capability(
        self,
        request: CapabilityExecutionRequest,
        tenant: TenantContext | None,
    ) -> CapabilityExecutionResult:
        if tenant is None:
            raise PermissionError(
                "Authenticated tenant context is required for capability execution."
            )

        return self._executor.execute(
            request,
            tenant=tenant,
        )

    @staticmethod
    def _confirmation_message(
        request: CapabilityExecutionRequest,
        confirmation_id: str,
    ) -> str:
        message = (
            "Confirmation required before executing "
            f"{request.capability.value}.{request.operation}. "
        )
        if (
            request.capability.value == "memory"
            and request.operation == "save"
        ):
            content = request.arguments.get("content")
            if isinstance(content, str):
                message += f"Proposed memory: {content!r}. "
        return message + f"Confirmation ID: {confirmation_id}"

    @staticmethod
    def _result_message(
        result: CapabilityExecutionResult,
    ) -> str:
        if result.success:
            if result.data is None:
                return (
                    "The requested operation completed successfully."
                )

            if isinstance(result.data, str):
                return result.data

            return str(result.data)

        return result.error or "The requested operation failed."
