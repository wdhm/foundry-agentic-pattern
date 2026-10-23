"""Opt-in Activity adapter for personal Teams approvals; no model or tool bypass."""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from agent_framework import AgentSession, Message
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.activity import ActivityAgentServerHost
from azure.ai.agentserver.core import get_request_context
from azure.ai.agentserver.core.storage import FoundryStateStore
from azure.ai.agentserver.invocations import InvocationAgentServerHost
from microsoft_agents.activity import Activity, Attachment, ResourceResponse
from microsoft_agents.hosting.core import TurnContext, TurnState
from pydantic import Field, ValidationError, model_validator
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from contracts.models import ContractModel, NonBlank

from .approval import COMMAND, InspectCall, PendingCall, ProposeCall, ProposeResult, ToolApprovalAgent
from .channel_policy import SharedReviewScope, TeamsChannelPolicy
from .channel_reviews import ChannelReviews, MemberCheck
from .conversation import ConversationRouter, ConversationService, structured_command
from .teams_card import CARD_TYPE, card, review_card, text

if TYPE_CHECKING:
    from .push_flow import PushFlow

LOGGER = logging.getLogger(__name__)
BINDING_STORE = "documentation-teams-approvals-v1"


class CardAction(ContractModel):
    interface_version: Literal["1.0.0"]
    action: Literal["approve", "reject", "edit", "modify", "inspect", "details"]
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


class EnableChannelNotifications(ContractModel):
    interface_version: Literal["1.0.0"]
    action: Literal["enable_channel_notifications"]


class ChannelBinding(ContractModel):
    tenant_id: UUID
    aad_object_id: UUID
    conversation_id: NonBlank
    platform_session_id: NonBlank
    owner: NonBlank
    shared_scope: SharedReviewScope | None = None


class TeamsApproval:
    def __init__(
        self, agent: ToolApprovalAgent, tenant_id: UUID, conversation: ConversationService | None = None,
        channel_policy: TeamsChannelPolicy | None = None,
    ) -> None:
        self.agent = agent
        self.tenant_id = tenant_id
        self.conversation = conversation
        self.push_flow: PushFlow | None = None
        if channel_policy is not None and channel_policy.tenant_id != tenant_id:
            raise ValueError("Channel review policy must use the configured Teams tenant.")
        self.channels = ChannelReviews(self, channel_policy) if channel_policy else None

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
            or conversation.conversation_type not in {"personal", "channel"}
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
        shared_scope = None
        if conversation.conversation_type == "channel":
            if self.channels is None:
                raise ValueError("Channel reviews are not enabled; use a personal Teams chat.")
            shared_scope = self.channels.policy.scope(activity)
        return ChannelBinding(
            tenant_id=self.tenant_id,
            aad_object_id=UUID(sender.aad_object_id),
            conversation_id=conversation.id,
            platform_session_id=platform.session_id,
            owner=self.agent.actor(),
            shared_scope=shared_scope,
        )

    async def record(self, pending_id: UUID, binding: ChannelBinding) -> PendingCall:
        if binding.shared_scope is not None and self.channels is not None:
            return await self.channels.record(pending_id, binding)
        response = await self.agent.execute(
            InspectCall(action="inspect", pending_id=pending_id).model_dump_json(),
            AgentSession(session_id=binding.platform_session_id),
        )
        return PendingCall.model_validate_json(response[0].text or "")

    async def save_binding(self, record: PendingCall, binding: ChannelBinding) -> None:
        if binding.shared_scope is not None and self.channels is not None:
            self.channels.authorize(binding, record)
            return
        store = await FoundryStateStore.get_or_create(BINDING_STORE, user_isolation=True)
        async with store:
            await store.create_item(str(record.pending_id), binding.model_dump(mode="json"))

    async def check_binding(self, pending_id: UUID, binding: ChannelBinding) -> None:
        if binding.shared_scope is not None and self.channels is not None:
            await self.channels.record(pending_id, binding)
            return
        store = await FoundryStateStore.get_or_create(BINDING_STORE, user_isolation=True)
        async with store:
            stored = await store.get_item(str(pending_id))
            if stored is None or ChannelBinding.model_validate(stored.value) != binding:
                raise ValueError("This card belongs to another user, conversation or session, or predates Teams cards.")

    async def verify_member(self, context: TurnContext, expected: ChannelBinding) -> None:
        from microsoft_agents.hosting.core.connector import ConnectorClientBase, TeamsConnectorClient

        if self.binding(context.activity) != expected:
            raise ValueError("Teams member lookup context differs from the acting user or channel.")
        sender = context.activity.from_property
        conversation = context.activity.conversation
        if sender is None or not sender.id or conversation is None or not conversation.id:
            raise ValueError("Current channel membership cannot be verified without sender/conversation IDs.")
        # The SDK registers this service under its abstract base-class key.
        connector = context.services.get(ConnectorClientBase)  # type: ignore[type-abstract]
        if connector is None:
            raise ValueError("Teams membership service is unavailable; no decision can be authorized.")
        async with asyncio.timeout(20):
            if expected.shared_scope is None or not isinstance(connector, TeamsConnectorClient):
                raise ValueError("Teams channel metadata service is unavailable; no decision can be authorized.")
            scope = expected.shared_scope
            channels = await connector.fetch_channel_list(scope.team_id)
            matches = [channel for channel in channels if channel.id == scope.channel_id]
            if len(matches) != 1:
                raise ValueError("Configured channel was not uniquely confirmed by the Teams bot.")
            kind = matches[0].type
            # Teams documents that the General channel ID equals the team ID.
            # Otherwise require an explicit standard-channel type from the service.
            if (
                kind is not None and kind.lower() != "standard"
                or kind is None and scope.channel_id != scope.team_id
            ):
                raise ValueError("Approvals require a verified standard channel; channel type was not confirmed.")
            member = await connector.conversations.get_conversation_member(conversation.id, sender.id)
        if (
            member.id != sender.id or not member.aad_object_id
            or UUID(member.aad_object_id) != expected.aad_object_id
        ):
            raise ValueError("Teams roster does not confirm the acting user's current membership.")

    async def resolve_channel_team(self, context: TurnContext) -> None:
        """Fill only missing team metadata from the authenticated bot connector."""
        from microsoft_agents.hosting.core.connector import ConnectorClientBase, TeamsConnectorClient

        if self.channels is None or self.channels.policy.team_aad_group_id is None:
            return
        activity = context.activity
        data = activity.channel_data
        if not isinstance(data, dict):
            raise ValueError("Teams channel metadata is missing.")
        team, channel, tenant = (data.get(key) for key in ("team", "channel", "tenant"))
        if not isinstance(team, dict) or not isinstance(channel, dict) or not isinstance(tenant, dict):
            raise ValueError("Teams channel metadata has an invalid shape.")
        if (
            tenant.get("id") != str(self.tenant_id)
            or channel.get("id") != self.channels.policy.channel_id
            or not isinstance(team.get("id"), str) or not team["id"]
        ):
            raise ValueError("Team lookup is restricted to the configured tenant and channel.")
        if team.get("aadGroupId"):
            return  # A conflicting supplied value is rejected by binding, never overwritten.
        platform = get_request_context()
        if (
            not os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT") or not platform.user_id
            or not platform.call_id or not platform.session_id or str(activity.channel_id) != "msteams"
        ):
            raise ValueError("Team lookup requires an authenticated Teams platform request.")
        connector = context.services.get(ConnectorClientBase)  # type: ignore[type-abstract]
        if not isinstance(connector, TeamsConnectorClient):
            raise ValueError("Teams team metadata service is unavailable; cannot verify the channel.")
        async with asyncio.timeout(20):
            details = await connector.fetch_team_details(team["id"])
        if (
            details.id != team["id"] or not details.aad_group_id
            or UUID(details.aad_group_id) != self.channels.policy.team_aad_group_id
        ):
            raise ValueError("The bot's team lookup does not match the configured Entra group.")
        # Identity still comes from the signed turn. Only service-confirmed team
        # metadata is filled; user/card fields never supply the missing group.
        activity.channel_data = {**data, "team": {**team, "aadGroupId": details.aad_group_id}}

    async def render(self, record: PendingCall) -> dict[str, Any]:
        if self.push_flow is not None:
            return await self.push_flow.render_pending(record)
        return review_card(record, self.agent.policy.content_parameter)

    async def handle(
        self, activity: Activity, *, member_check: MemberCheck | None = None,
    ) -> dict[str, Any] | str:
        binding = self.binding(activity)
        session = AgentSession(session_id=binding.platform_session_id)
        if activity.value is not None:
            try:
                submitted = CardAction.model_validate(activity.value)
            except ValidationError:
                raise ValueError("Invalid card action. Reopen the proposal and use its buttons.") from None
            if binding.shared_scope is not None and self.channels is not None:
                return await self.channels.handle(submitted, binding, member_check=member_check)
            await self.check_binding(submitted.pending_id, binding)
            record = await self.record(submitted.pending_id, binding)
            if record.args_hash != submitted.args_hash:
                raise ValueError("Card arguments do not match the stored proposal. Reopen the correct card.")
            if submitted.action == "inspect":
                return await self.render(record)
            if submitted.action == "details":
                return review_card(record, self.agent.policy.content_parameter)
            self.agent.check_pending(record.model_dump())
            self.agent.check_record(record)
            if self.push_flow is not None and submitted.action != "reject":
                await self.push_flow.require_current(record.pending_id)
            if submitted.action == "edit":
                return review_card(record, self.agent.policy.content_parameter, view="edit")
            if submitted.action == "modify":
                bundle = (
                    await self.push_flow.revision_draft(record, submitted.content or "")
                    if self.push_flow is not None else None
                )
                modify_command = json.dumps({
                    "action": "modify", "pending_id": str(record.pending_id),
                    "content": submitted.content, "feedback": submitted.feedback,
                    **({
                        "review_draft": bundle.page.model_dump(mode="json"),
                        "review_notes": bundle.notes.model_dump(mode="json") if bundle.notes else None,
                    } if bundle is not None else {}),
                })
                response = await self.agent.execute(modify_command, session)
                approval = next(item for item in response if item.type == "function_approval_request")
                replacement = await self.record(UUID(approval.id or ""), binding)
                if self.push_flow is not None:
                    await self.push_flow.inherit_event(record.pending_id, replacement.pending_id, bundle)
                await self.save_binding(replacement, binding)
                return await self.render(replacement)
            # Ignore all client-supplied tool arguments. Reconstitute the native
            # decision from the owner/session-checked server-side pending call.
            decision = record.approval().to_function_approval_response(submitted.action == "approve")
            response = await self.agent.execute(Message("user", [decision]), session)
            result = PendingCall.model_validate_json(response[0].text or "")
            return await self.render(result)

        message = (activity.text or "").strip()
        if message.lower() in {"", "help", "start", "hej", "hi"}:
            actions = []
            if (
                binding.shared_scope is not None and self.channels is not None
                and self.channels.policy.show_decisions(binding.aad_object_id)
            ):
                actions.append({
                    "type": "Action.Submit", "title": "Enable channel notifications", "associatedInputs": "none",
                    "data": {"interface_version": "1.0.0", "action": "enable_channel_notifications"},
                })
            return card([
                text("Documentation approval", weight="Bolder", size="Medium"),
                text("Review a proposed tool call, then Approve, Modify or Reject. Opening a card never writes."),
                text(
                    (
                        "Ask a question about the configured sources, such as: What does Order Sync do? "
                        "Chat is read-only; publishing still requires the review card. "
                        "Use show <pending-id> to reopen a card."
                    ) if self.conversation is not None else (
                        "For this workshop, submit a structured propose/propose_result command "
                        "from the assessment caller, "
                        "or type: show <pending-id> to reopen a card created in this Teams conversation."
                    )
                ),
                *(
                    [text("Channel reviews: @mention me with enable notifications in the configured channel. "
                          "The configured reviewer rule is checked before enabling notifications or deciding.")]
                    if binding.shared_scope is not None else
                    [text("For repository notifications, send connect repo once in this personal chat.")]
                    if self.push_flow is not None else []
                ),
            ], actions)
        pending_id = None
        if message.startswith("show "):
            try:
                pending_id = UUID(message.removeprefix("show ").strip())
            except ValueError:
                if self.conversation is None:
                    raise
        if pending_id is not None:
            await self.check_binding(pending_id, binding)
            pending = await self.record(pending_id, binding)
            return (
                await self.channels.render(pending, binding) if binding.shared_scope and self.channels
                else await self.render(pending)
            )
        if self.conversation is not None and not structured_command(message):
            conversation = self.conversation
            if binding.shared_scope is not None and self.push_flow is not None:
                conversation = await self.push_flow.channel_conversation(binding, conversation)
            return await conversation.answer(
                message, owner=binding.owner, session_id=binding.platform_session_id,
                channel=(
                    f"teams:{binding.tenant_id}:{binding.aad_object_id}:{binding.shared_scope.model_dump_json()}"
                    if binding.shared_scope else
                    f"teams:{binding.tenant_id}:{binding.aad_object_id}:{binding.conversation_id}"
                ),
            )
        if binding.shared_scope is not None:
            raise ValueError("Channel proposals come from merged-PR reviews, not pasted approval commands.")
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


class PushTeamsHost(InvocationAgentServerHost, TeamsResponsesHost):
    """Explicit opt-in pipeline route; existing Teams/Responses routes retained."""


def create_teams_server(
    agent: ToolApprovalAgent, *, conversation: ConversationService | None = None,
    channel_policy: TeamsChannelPolicy | None = None,
) -> TeamsResponsesHost:
    if os.environ.get("DOCUMENTATION_ENABLE_TEAMS") != "true":
        raise ValueError("Teams requires explicit DOCUMENTATION_ENABLE_TEAMS=true.")
    tenant = os.environ.get("DOCUMENTATION_TEAMS_TENANT_ID")
    if not tenant:
        raise ValueError("Teams requires DOCUMENTATION_TEAMS_TENANT_ID.")
    channel_policy = channel_policy or TeamsChannelPolicy.from_environment()
    handler = TeamsApproval(agent, UUID(tenant), conversation, channel_policy)
    enabled = os.environ.get("DOCUMENTATION_ENABLE_PUSH_FLOW") == "true"
    if channel_policy is not None and not enabled:
        raise ValueError("Channel reviews require the merged-PR push flow.")
    responses_agent = ConversationRouter(agent, conversation) if conversation is not None else agent
    host = (PushTeamsHost if enabled else TeamsResponsesHost)(agent=responses_agent, history_source="agent")
    if enabled:
        from microsoft_agents.activity import ConversationReference

        from .assessment import AssessmentAgent
        from .channel_delivery import create_channel_post
        from .draft_reader import ToolboxDraftReader
        from .push_flow import PushFlow, PushPolicy, PushPreflight, PushRequest, ReviewAction
        from .settings import AssessmentSettings
        from .wiki_drafts import WikiDraftPublisher

        policy = PushPolicy.from_environment()
        read_toolbox = os.environ.get("DOCUMENTATION_PUSH_READ_TOOLBOX")
        if not read_toolbox:
            raise ValueError("Push flow requires a separately pinned DOCUMENTATION_PUSH_READ_TOOLBOX.")
        settings = AssessmentSettings.from_environment({**os.environ, "TOOLBOX_ENDPOINT": read_toolbox})
        from contracts.repositories import azure_repository

        repo = azure_repository(policy.repository_url)
        if settings.ado_organization != repo.organization or settings.ado_project != repo.project:
            raise ValueError("Push repository must match the assessment organization/project.")

        async def notify(
            reference: ConversationReference, output: dict[str, Any],
            channel_scope: SharedReviewScope | None = None,
        ) -> SharedReviewScope | None:
            app_id = os.environ.get("FOUNDRY_AGENT_INSTANCE_CLIENT_ID")
            if not app_id:
                raise ValueError("Foundry instance identity is required for proactive Teams delivery.")

            async def send(context: TurnContext) -> None:
                await context.send_activity(Activity(
                    type="message", text="Documentation review ready",
                    attachments=[Attachment(content_type=CARD_TYPE, content=output)],
                ))

            adapter = host.adapter
            if adapter is None:
                raise ValueError("Activity adapter is not configured.")
            if reference.conversation is not None and reference.conversation.conversation_type == "channel":
                if channel_policy is None or channel_scope is None:
                    raise ValueError("Channel notifications require an explicit channel policy.")
                channel_policy.require_scope(channel_scope)
                result: SharedReviewScope | None = None

                async def created(context: TurnContext) -> None:
                    nonlocal result
                    async with asyncio.timeout(60):
                        result = await create_channel_post(context, channel_scope, output)

                await adapter.continue_conversation(app_id, reference.get_continuation_activity(), created)
                if result is None:
                    raise ValueError("Channel notification outcome is unknown; inspect before any retry.")
                return result
            await adapter.continue_conversation(app_id, reference.get_continuation_activity(), send)
            return None

        draft_reader = (
            ToolboxDraftReader(settings) if policy.merged_pr_drafts and policy.draft_storage == "git_branch" else None
        )
        wiki_publisher = None
        if policy.draft_storage == "wiki":
            if agent.wiki_reader is None:
                raise ValueError("Wiki draft publication requires the existing-page reader.")
            wiki_publisher = WikiDraftPublisher(agent.policy, agent.wiki_reader)
        flow = PushFlow(
            policy, handler, AssessmentAgent(settings), notify,
            read_draft=draft_reader,
            read_notes=draft_reader.read_notes if draft_reader is not None else None,
            read_wiki=agent.wiki_reader,
            wiki_publisher=wiki_publisher,
        )
        handler.push_flow = flow

        async def on_push(request: Request) -> Response:
            try:
                flow.require_caller()
                payload = await request.body()
                if len(payload) > 8192:
                    raise ValueError("Push request exceeds size limit.")
                parsed = json.loads(payload)
                if isinstance(parsed, dict) and parsed.get("action") == "preflight":
                    PushPreflight.model_validate(parsed)
                    return JSONResponse({"state": "caller_verified", "assessment_run": False})
                if isinstance(parsed, dict) and parsed.get("action") == "draft_published":
                    from contracts.drafts import DraftPublished

                    return JSONResponse(await flow.publish_draft(DraftPublished.model_validate(parsed)))
                push = PushRequest.model_validate_json(payload)
                result = await flow.process(push)
                return JSONResponse(result)
            except PermissionError:
                LOGGER.warning("Push caller rejected.")
                return JSONResponse({"error": "Caller not authorized."}, status_code=403)
            except ValueError as exc:
                LOGGER.warning("Push request rejected (%s).", type(exc).__name__)
                message = str(exc) if not isinstance(exc, ValidationError) else "Invalid push payload."
                return JSONResponse({"error": message}, status_code=400)
            except Exception as exc:
                LOGGER.error(
                    "Push flow failed (%s); inspect durable state, do not automatically retry.", type(exc).__name__
                )
                return JSONResponse({"error": "Processing failed; inspect durable event state before retry."},
                                    status_code=500)

        host.invoke_handler(on_push)

    @host.agent_app.activity("message")
    async def on_message(context: TurnContext, state: TurnState) -> None:
        # Action.Submit is a message with value, not a five-second Action.Execute
        # invoke. A retried delivery still goes through the runtime's atomic claim.
        try:
            activity = context.activity
            member_check: MemberCheck | None = None
            if activity.conversation is not None and activity.conversation.conversation_type == "channel":
                await handler.resolve_channel_team(context)
                binding = handler.binding(activity)
                scope = binding.shared_scope
                if scope is None:
                    raise ValueError("Channel thread identity is missing.")

                async def thread_replies(
                    turn: TurnContext, activities: list[Activity],
                    send: Callable[[], Awaitable[list[ResourceResponse]]],
                ) -> list[ResourceResponse]:
                    # The SDK applies its own reply_to_id after send_activity.
                    # This public send hook runs after that mapping.
                    for outgoing in activities:
                        outgoing.reply_to_id = scope.thread_id
                    return await send()

                context.on_send_activities(thread_replies)

                async def current_member(expected: ChannelBinding) -> None:
                    await handler.verify_member(context, expected)

                member_check = current_member
                # Teams delivers ordinary channel messages on @mention. Remove
                # only this bot's mention, never infer identity from message text.
                activity.text = TurnContext.remove_recipient_mention(activity)
            flow = handler.push_flow
            output: dict[str, Any] | str
            if (
                flow is not None and (activity.text or "").strip().lower() in {"connect repo", "enable notifications"}
                and activity.value is None
            ):
                output = await flow.register(activity, member_check=member_check)
            elif (
                flow is not None and isinstance(activity.value, dict)
                and activity.value.get("action") == "enable_channel_notifications"
            ):
                EnableChannelNotifications.model_validate(activity.value)
                if handler.channels is None or handler.binding(activity).shared_scope is None:
                    raise ValueError("Enable channel notifications from the configured channel.")
                output = await flow.register(activity, member_check=member_check)
            elif (
                flow is not None and isinstance(activity.value, dict)
                and activity.value.get("action") == "review_push"
            ):
                review = ReviewAction.model_validate(activity.value)
                output = await flow.open_review(activity, review.event_id)
            elif (
                flow is not None and activity.value is None
                and (activity.text or "").strip().startswith("retry notification ")
            ):
                event_id = UUID((activity.text or "").strip().removeprefix("retry notification ").strip())
                output = await flow.retry_channel_notification(activity, event_id, member_check=member_check)
            elif flow is not None and activity.value is None and (activity.text or "").startswith("review "):
                output = await flow.open_review(activity, UUID((activity.text or "").removeprefix("review ").strip()))
            else:
                output = await handler.handle(activity, member_check=member_check)
        except ValidationError:
            LOGGER.warning("Teams approval request failed schema validation.")
            await context.send_activity(
                "Request rejected: invalid message, proposal or card data. Contact the operator."
            )
            return
        except ValueError as exc:
            LOGGER.warning("Teams approval request not completed: %s", type(exc).__name__)
            await context.send_activity(
                f"Request not completed: {exc} "
                "If this followed Approve, use show <pending-id> to check the persisted outcome before any retry."
            )
            return
        if isinstance(output, str):
            await context.send_activity(Activity(type="message", text=output))
        else:
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
