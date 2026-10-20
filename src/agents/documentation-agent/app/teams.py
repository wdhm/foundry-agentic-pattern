"""Opt-in Activity adapter for personal Teams approvals; no model or tool bypass."""

import json
import logging
import os
from typing import Annotated, Any, Literal
from uuid import UUID

from agent_framework import AgentSession, Message
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.activity import ActivityAgentServerHost
from azure.ai.agentserver.core import get_request_context
from azure.ai.agentserver.core.storage import FoundryStateStore
from microsoft_agents.activity import Activity, Attachment
from microsoft_agents.hosting.core import TurnContext, TurnState
from pydantic import Field, ValidationError, model_validator

from contracts.models import ContractModel, NonBlank

from .approval import COMMAND, InspectCall, PendingCall, ProposeCall, ProposeResult, ToolApprovalAgent
from .teams_card import CARD_TYPE, card, review_card, text

LOGGER = logging.getLogger(__name__)
BINDING_STORE = "documentation-teams-approvals-v1"


class CardAction(ContractModel):
    interface_version: Literal["1.0.0"]
    action: Literal["approve", "reject", "edit", "modify", "inspect"]
    pending_id: UUID
    args_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    content: Annotated[NonBlank, Field(max_length=16000)] | None = None
    feedback: Annotated[NonBlank, Field(max_length=1000)] | None = None

    @model_validator(mode="after")
    def modification_only(self) -> "CardAction":
        if self.action == "modify":
            if self.content is None or self.feedback is None:
                raise ValueError("Modify requires replacement content and feedback.")
        elif self.content is not None or self.feedback is not None:
            raise ValueError("Only Modify accepts replacement content or feedback.")
        return self


class ChannelBinding(ContractModel):
    tenant_id: UUID
    aad_object_id: UUID
    conversation_id: NonBlank
    platform_session_id: NonBlank
    owner: NonBlank


class TeamsApproval:
    def __init__(self, agent: ToolApprovalAgent, tenant_id: UUID) -> None:
        self.agent = agent
        self.tenant_id = tenant_id

    def binding(self, activity: Activity) -> ChannelBinding:
        platform = get_request_context()
        # Foundry validates the inbound channel token. Only its request context
        # establishes the runtime actor; Activity.value/text never supplies identity.
        if not os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT") or not platform.user_id or not platform.call_id:
            raise ValueError("Teams approvals require authenticated Foundry platform context.")
        if not platform.session_id:
            raise ValueError("Teams approval is missing the platform session.")
        if str(activity.channel_id) != "msteams":
            raise ValueError("Only the Teams channel is supported.")
        conversation = activity.conversation
        sender = activity.from_property
        if (
            conversation is None
            or conversation.conversation_type != "personal"
            or not conversation.id
            or sender is None
            or not sender.aad_object_id
        ):
            raise ValueError("Use a personal Teams chat with an identified signed-in user.")
        channel = activity.channel_data
        tenant = channel.get("tenant") if isinstance(channel, dict) else None
        tenant_value = tenant.get("id") if isinstance(tenant, dict) else None
        if not isinstance(tenant_value, str) or UUID(tenant_value) != self.tenant_id:
            raise ValueError("Teams tenant does not match the configured tenant.")
        if conversation.tenant_id and UUID(conversation.tenant_id) != self.tenant_id:
            raise ValueError("Conversation tenant does not match the configured tenant.")
        return ChannelBinding(
            tenant_id=self.tenant_id,
            aad_object_id=UUID(sender.aad_object_id),
            conversation_id=conversation.id,
            platform_session_id=platform.session_id,
            owner=self.agent.actor(),
        )

    async def record(self, pending_id: UUID, binding: ChannelBinding) -> PendingCall:
        response = await self.agent.execute(
            InspectCall(action="inspect", pending_id=pending_id).model_dump_json(),
            AgentSession(session_id=binding.platform_session_id),
        )
        return PendingCall.model_validate_json(response[0].text or "")

    async def save_binding(self, record: PendingCall, binding: ChannelBinding) -> None:
        store = await FoundryStateStore.get_or_create(BINDING_STORE, user_isolation=True)
        async with store:
            await store.create_item(str(record.pending_id), binding.model_dump(mode="json"))

    async def check_binding(self, pending_id: UUID, binding: ChannelBinding) -> None:
        store = await FoundryStateStore.get_or_create(BINDING_STORE, user_isolation=True)
        async with store:
            stored = await store.get_item(str(pending_id))
            if stored is None or ChannelBinding.model_validate(stored.value) != binding:
                raise ValueError("This card belongs to another user, conversation or session, or predates Teams cards.")

    async def handle(self, activity: Activity) -> dict[str, Any]:
        binding = self.binding(activity)
        session = AgentSession(session_id=binding.platform_session_id)
        if activity.value is not None:
            try:
                submitted = CardAction.model_validate(activity.value)
            except ValidationError:
                raise ValueError("Invalid card action. Reopen the proposal and use its buttons.") from None
            await self.check_binding(submitted.pending_id, binding)
            record = await self.record(submitted.pending_id, binding)
            if record.args_hash != submitted.args_hash:
                raise ValueError("Card arguments do not match the stored proposal. Reopen the correct card.")
            if submitted.action == "inspect":
                return review_card(record, self.agent.policy.content_parameter)
            self.agent.check_pending(record.model_dump())
            self.agent.check_record(record)
            if submitted.action == "edit":
                return review_card(record, self.agent.policy.content_parameter, view="edit")
            if submitted.action == "modify":
                modify_command = json.dumps({
                    "action": "modify", "pending_id": str(record.pending_id),
                    "content": submitted.content, "feedback": submitted.feedback,
                })
                response = await self.agent.execute(modify_command, session)
                approval = next(item for item in response if item.type == "function_approval_request")
                replacement = await self.record(UUID(approval.id or ""), binding)
                await self.save_binding(replacement, binding)
                return review_card(replacement, self.agent.policy.content_parameter)
            # Ignore all client-supplied tool arguments. Reconstitute the native
            # decision from the owner/session-checked server-side pending call.
            decision = record.approval().to_function_approval_response(submitted.action == "approve")
            response = await self.agent.execute(Message("user", [decision]), session)
            result = PendingCall.model_validate_json(response[0].text or "")
            return review_card(result, self.agent.policy.content_parameter)

        message = (activity.text or "").strip()
        if message.lower() in {"", "help", "start", "hej", "hi"}:
            return card([
                text("Documentation approval", weight="Bolder", size="Medium"),
                text("Review a proposed tool call, then Approve, Modify or Reject. Opening a card never writes."),
                text(
                    "For this workshop, submit a structured propose/propose_result command from the assessment caller, "
                    "or type: show <pending-id> to reopen a card created in this Teams conversation."
                ),
            ])
        if message.startswith("show "):
            pending_id = UUID(message.removeprefix("show ").strip())
            await self.check_binding(pending_id, binding)
            return review_card(await self.record(pending_id, binding), self.agent.policy.content_parameter)
        try:
            command = COMMAND.validate_json(message)
        except ValidationError:
            raise ValueError(
                "Use a valid proposal JSON command, help, or show <pending-id>; decisions use card buttons."
            ) from None
        if not isinstance(command, (ProposeCall, ProposeResult)):
            raise ValueError("Use the card buttons for decisions and changes, or show <pending-id> for status.")
        response = await self.agent.execute(command.model_dump_json(), session)
        approval = next(item for item in response if item.type == "function_approval_request")
        record = await self.record(UUID(approval.id or ""), binding)
        await self.save_binding(record, binding)
        return review_card(record, self.agent.policy.content_parameter)


class TeamsResponsesHost(ActivityAgentServerHost, ResponsesHostServer):  # type: ignore[misc]
    """SDK host composition; the pinned Responses SDK lacks typing metadata."""


def create_teams_server(agent: ToolApprovalAgent) -> TeamsResponsesHost:
    if os.environ.get("DOCUMENTATION_ENABLE_TEAMS") != "true":
        raise ValueError("Teams requires explicit DOCUMENTATION_ENABLE_TEAMS=true.")
    tenant = os.environ.get("DOCUMENTATION_TEAMS_TENANT_ID")
    if not tenant:
        raise ValueError("Teams requires DOCUMENTATION_TEAMS_TENANT_ID.")
    handler = TeamsApproval(agent, UUID(tenant))
    host = TeamsResponsesHost(agent=agent, history_source="agent")

    @host.agent_app.activity("message")
    async def on_message(context: TurnContext, state: TurnState) -> None:
        # Action.Submit is a message with value, not a five-second Action.Execute
        # invoke. A retried delivery still goes through the runtime's atomic claim.
        try:
            output = await handler.handle(context.activity)
        except ValidationError:
            LOGGER.warning("Teams approval request failed schema validation.")
            await context.send_activity("Request rejected: invalid proposal or card data. Contact the operator.")
            return
        except ValueError as exc:
            LOGGER.warning("Teams approval request not completed: %s", type(exc).__name__)
            await context.send_activity(
                f"Request not completed: {exc} "
                "If this followed Approve, use show <pending-id> to check the persisted outcome before any retry."
            )
            return
        await context.send_activity(Activity(
            type="message",
            text="Documentation approval",
            attachments=[Attachment(content_type=CARD_TYPE, content=output)],
        ))

    @host.agent_app.error
    async def on_error(context: TurnContext, error: Exception) -> None:
        LOGGER.error("Teams approval handler failed (%s); inspect persisted status before retry.", type(error).__name__)
        await context.send_activity(
            "The request could not be completed. If you pressed Approve, the write outcome may be unknown. "
            "Do not submit a replacement or retry the write. Use show <pending-id> and reconcile the target. "
            "Reference this Teams message when contacting the operator."
        )

    return host
