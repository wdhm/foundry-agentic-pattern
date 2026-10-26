"""Shared review state accessible only through authenticated, scoped Teams turns."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from azure.ai.agentserver.core.storage import FoundryStateStore

from .approval import PendingCall, ProposeCall, ToolApprovalAgent
from .channel_policy import TeamsChannelPolicy
from .teams_card import card, review_card, text

if TYPE_CHECKING:
    from .teams import CardAction, ChannelBinding, TeamsApproval

LOGGER = logging.getLogger(__name__)
STORE = "documentation-channel-approvals-v1"
MemberCheck = Callable[["ChannelBinding"], Awaitable[None]]


class ChannelReviews:
    def __init__(self, teams: "TeamsApproval", policy: TeamsChannelPolicy) -> None:
        self.teams = teams
        self.policy = policy.model_copy(deep=True)

    def authorize(self, binding: "ChannelBinding", record: PendingCall | None = None, *, decide: bool = False) -> None:
        if binding.shared_scope is None:
            raise ValueError("Shared reviews require a verified channel binding.")
        self.policy.require_scope(binding.shared_scope)
        if record is not None and record.shared_scope != binding.shared_scope:
            raise ValueError("This proposal belongs to another channel or review thread.")
        if decide:
            self.policy.require_reviewer(binding.aad_object_id)

    async def verify_decision(
        self, binding: "ChannelBinding", record: PendingCall | None, member_check: MemberCheck | None,
    ) -> None:
        self.authorize(binding, record, decide=True)
        if self.policy.reviewer_mode == "channel_members":
            if member_check is None:
                raise ValueError("A current Teams channel membership lookup is required before deciding.")
            await member_check(binding)
            if record is not None:
                record.membership_checked_at = datetime.now(UTC)

    async def record(self, pending_id: UUID, binding: "ChannelBinding") -> PendingCall:
        self.authorize(binding)
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            item = await store.get_item(str(pending_id))
            if item is None:
                raise ValueError("Unknown shared channel review.")
            record = PendingCall.model_validate(item.value)
            self.authorize(binding, record)
            return record

    async def create(self, proposal: ProposeCall, binding: "ChannelBinding") -> PendingCall:
        self.authorize(binding)
        pending = await self.teams.agent.proposal(proposal, binding.owner, binding.platform_session_id)
        pending.shared_scope = binding.shared_scope
        pending.runtime_version = "0.7.0"
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            await store.create_item(str(pending.pending_id), pending.model_dump(mode="json"))
        return pending

    async def render(self, pending: PendingCall, binding: "ChannelBinding") -> dict[str, Any]:
        self.authorize(binding, pending)
        output = await self.teams.render(pending)
        if not self.policy.show_decisions(binding.aad_object_id):
            output["actions"] = [a for a in output.get("actions", []) if a.get("data", {}).get("action") == "inspect"]
            output["body"].append(text("Read-only view. Only the configured channel reviewers can decide."))
        else:
            output["body"].append(text("Shared review: the first valid decision wins. Later clicks show its status."))
        if pending.decided_by_aad_id:
            output["body"].append(text(f"Decision by (Entra object ID): {pending.decided_by_aad_id}"))
        return card(output["body"], output.get("actions"))

    async def handle(
        self, submitted: "CardAction", binding: "ChannelBinding", *, member_check: MemberCheck | None = None,
    ) -> dict[str, Any]:
        pending = await self.record(submitted.pending_id, binding)
        if submitted.args_hash != pending.args_hash:
            raise ValueError("Card arguments do not match the shared proposal.")
        if submitted.action == "inspect":
            return await self.render(pending, binding)
        if submitted.action == "details":
            # Viewers can inspect content but never receive actionable controls.
            output = review_card(pending, self.teams.agent.policy.content_parameter)
            if not self.policy.show_decisions(binding.aad_object_id):
                output.pop("actions", None)
            return output
        await self.verify_decision(binding, pending, member_check)
        if pending.status != "pending":
            return await self.render(pending, binding)
        self.teams.agent.check_record(pending)
        flow = self.teams.push_flow
        if flow is None:
            raise ValueError("Shared review requires the configured merged-PR flow.")
        await flow.require_current(pending.pending_id, required=True)
        if submitted.action == "edit":
            return review_card(pending, self.teams.agent.policy.content_parameter, view="edit")
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            if submitted.action == "modify":
                current = await store.get_item(str(pending.pending_id))
                if current is None:
                    raise ValueError("Shared review disappeared.")
                pending = PendingCall.model_validate(current.value)
                await self.verify_decision(binding, pending, member_check)
                if pending.status != "pending":
                    return await self.render(pending, binding)
                if pending.expires_at <= datetime.now(UTC):
                    raise ValueError("Approval expired; create a new review.")
                # Claim before publishing even a draft revision. An overlapping
                # approval cannot publish the original after this CAS succeeds.
                pending.status = "modified"
                pending.decided_by = binding.owner
                pending.decided_by_aad_id = binding.aad_object_id
                pending.decided_at = datetime.now(UTC)
                pending.feedback = submitted.feedback
                try:
                    claimed = await ToolApprovalAgent.replace(
                        store, str(pending.pending_id), pending.model_dump(mode="json"), current.etag,
                    )
                except ValueError:
                    latest = await self.record(pending.pending_id, binding)
                    if latest.status != "pending":
                        return await self.render(latest, binding)
                    raise
                try:
                    bundle = await flow.revision_draft(pending, submitted.content or "")
                    if bundle is None:
                        raise ValueError("Channel modification requires wiki draft revision support.")
                    replacement = await self.teams.agent.proposal(
                        ProposeCall(
                            action="propose", run_id=pending.run_id, content=submitted.content or "",
                            evidence=pending.evidence, expected_wiki_etag=str(pending.arguments["etag"]),
                            review_draft=bundle.page, review_notes=bundle.notes,
                        ), binding.owner, binding.platform_session_id, pending.origin,
                    )
                    replacement.shared_scope = binding.shared_scope
                    replacement.runtime_version = "0.7.0"
                    await store.create_item(str(replacement.pending_id), replacement.model_dump(mode="json"))
                    pending.replacement_id = replacement.pending_id
                    await ToolApprovalAgent.replace(
                        store, str(pending.pending_id), pending.model_dump(mode="json"), claimed.etag,
                    )
                    await flow.inherit_event(pending.pending_id, replacement.pending_id, bundle)
                except Exception as exc:
                    LOGGER.error("Shared review revision %s failed (%s); original remains void.",
                                 pending.pending_id, type(exc).__name__)
                    raise
                return await self.render(replacement, binding)

            async def authorize(record: PendingCall) -> None:
                await self.verify_decision(binding, record, member_check)
                record.decided_by_aad_id = binding.aad_object_id

            decision = pending.approval().to_function_approval_response(submitted.action == "approve")
            try:
                decision_output = await self.teams.agent.decide(
                    store, decision, binding.owner, binding.platform_session_id, authorize_shared=authorize,
                )
            except ValueError:
                # A concurrent decision may have won the runtime's atomic claim.
                # Report only persisted state, never infer a successful write.
                current = await store.get_item(str(pending.pending_id))
                if current is not None:
                    latest = PendingCall.model_validate(current.value)
                    self.authorize(binding, latest)
                    if latest.status != "pending":
                        return await self.render(latest, binding)
                raise
        return await self.render(PendingCall.model_validate_json(decision_output[0].text or ""), binding)
