"""Main-push assessment inbox. Automation never impersonates the Teams reviewer."""

import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, Self
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from agent_framework import AgentSession
from azure.ai.agentserver.core import get_request_context
from azure.ai.agentserver.core.storage import FoundryStateStore, FoundryStorageConflictError
from microsoft_agents.activity import Activity, ConversationReference
from pydantic import Field, model_validator

from contracts.models import CommitSha, ContractModel, NonBlank
from contracts.repositories import azure_repository
from contracts.v1 import AgentRequest, AgentResult

from .approval import ProposeCall
from .approval_common import canonical_hash
from .teams import ChannelBinding, TeamsApproval
from .teams_card import card, review_card, text

LOGGER = logging.getLogger(__name__)
STORE = "documentation-push-flow-v1"


class PushPolicy(ContractModel):
    repository_url: NonBlank
    branch: Literal["refs/heads/main"] = "refs/heads/main"
    pipeline_id: Annotated[int, Field(strict=True, gt=0)]
    caller_id: UUID
    reviewer_aad_id: UUID
    source_paths: Annotated[list[NonBlank], Field(min_length=1, max_length=10)]
    wiki_page: NonBlank
    work_item_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(default_factory=list)
    documentation_standard_ref: NonBlank
    sandbox_page: Literal["/Workshop/Approval-Sandbox"] = "/Workshop/Approval-Sandbox"

    @model_validator(mode="after")
    def valid_sources(self) -> Self:
        repo = azure_repository(self.repository_url)
        UUID(repo.repository)
        if len(set(self.source_paths)) != len(self.source_paths):
            raise ValueError("Source paths must be unique.")
        for path in self.source_paths:
            if (
                path.startswith("/") or "\\" in path or "%" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                raise ValueError("Source paths must be unambiguous repository-relative files.")
        return self

    @classmethod
    def from_environment(cls) -> Self:
        path = os.environ.get("DOCUMENTATION_PUSH_POLICY")
        if not path:
            raise ValueError("Push automation requires DOCUMENTATION_PUSH_POLICY.")
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


class PushRequest(ContractModel):
    interface_version: Literal["1.0.0"]
    repository_url: NonBlank
    branch: Literal["refs/heads/main"]
    pipeline_id: Annotated[int, Field(strict=True, gt=0)]
    build_id: Annotated[int, Field(strict=True, gt=0)]
    commit_sha: CommitSha


class PushPreflight(ContractModel):
    interface_version: Literal["1.0.0"]
    action: Literal["preflight"]


class Recipient(ContractModel):
    binding: ChannelBinding
    reference: dict[str, Any]


class ReviewAction(ContractModel):
    interface_version: Literal["1.0.0"]
    action: Literal["review_push"]
    event_id: UUID


class Assessment(Protocol):
    async def assess(self, request: AgentRequest) -> AgentResult: ...


Notify = Callable[[ConversationReference, dict[str, Any]], Awaitable[None]]


def event_key(policy: PushPolicy, commit: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{policy.repository_url}|{policy.branch}|{commit}"))


def report_content(result: AgentResult) -> str:
    """Complete sandbox review document, not a guessed merge into the real wiki."""
    lines = [
        "# Documentation assessment review",
        "",
        "This sandbox page contains proposed documentation, not an automatic update to the integration wiki.",
        f"Assessment request: {result.request_id}",
        f"Status: {result.documentation_status}",
        "",
        "## Findings",
    ]
    lines.extend(f"- {finding.description}" for finding in result.findings)
    for change in result.proposed_changes:
        lines.extend([
            "", f"## Proposal for {change.target_page} / {change.target_section}", change.proposed_content,
        ])
    if result.missing_information:
        lines.extend(["", "## Information missing"])
        lines.extend(
            f"- {item.description} (expected source: {item.expected_source})" for item in result.missing_information
        )
    lines.extend(["", "## Evidence"])
    for evidence in result.evidence:
        lines.extend([f"- {evidence.id}: {evidence.uri}", f"  Version: {evidence.version}", f"  {evidence.excerpt}"])
    return "\n".join(lines) + "\n"


class PushFlow:
    def __init__(self, policy: PushPolicy, teams: TeamsApproval, assessor: Assessment, notify: Notify) -> None:
        self.policy = policy
        self.teams = teams
        self.assessor = assessor
        self.notify = notify
        if teams.agent.policy.fixed_arguments.get("path") != policy.sandbox_page:
            raise ValueError("Push flow may write only the reviewed sandbox, never the integration wiki.")

    async def store(self) -> FoundryStateStore:
        # Pipeline and reviewer need different identities. Access to this shared
        # inbox is mediated below, never by client-selected store keys or owners.
        return await FoundryStateStore.get_or_create(STORE, user_isolation=False)

    def reviewer(self, activity: Activity) -> ChannelBinding:
        binding = self.teams.binding(activity)
        if binding.aad_object_id != self.policy.reviewer_aad_id:
            raise ValueError("Only the configured reviewer can register or open push reviews.")
        return binding

    async def register(self, activity: Activity) -> dict[str, Any]:
        binding = self.reviewer(activity)
        url = urlsplit(activity.service_url or "")
        if (
            url.scheme != "https" or url.hostname != "smba.trafficmanager.net" or url.port not in {None, 443}
            or url.username or url.password or url.query or url.fragment
        ):
            raise ValueError("Only the verified public-cloud Teams Bot Connector service URL is supported.")
        reference = activity.get_conversation_reference()
        recipient = Recipient(
            binding=binding, reference=reference.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        store = await self.store()
        async with store:
            existing = await store.get_item("recipient")
            if existing is None:
                await store.create_item("recipient", recipient.model_dump(mode="json"))
            else:
                await store.set_item("recipient", recipient.model_dump(mode="json"), if_match=existing.etag)
        return card([
            text("Repository notifications connected", weight="Bolder", size="Medium"),
            text(f"Repository: {self.policy.repository_url}"),
            text("Main-branch changes will be assessed and sent to this personal chat."),
            text("Opening a review creates a new approval in your session. Automation never approves a write."),
        ])

    def require_caller(self) -> None:
        context = get_request_context()
        if (
            not os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT") or not context.call_id
            or context.user_id != str(self.policy.caller_id)
        ):
            raise PermissionError("Push endpoint requires the configured authenticated platform workload identity.")

    async def process(self, request: PushRequest) -> dict[str, Any]:
        self.require_caller()
        if (
            request.repository_url != self.policy.repository_url or request.branch != self.policy.branch
            or request.pipeline_id != self.policy.pipeline_id
        ):
            raise ValueError("Push repository, branch or pipeline does not match operator policy.")
        key = event_key(self.policy, request.commit_sha)
        store = await self.store()
        async with store:
            subscriber = await store.get_item("recipient")
            if subscriber is None:
                raise ValueError("Reviewer must send 'connect repo' in Teams before enabling the pipeline.")
            recipient = Recipient.model_validate(subscriber.value)
            if recipient.binding.aad_object_id != self.policy.reviewer_aad_id:
                raise ValueError("Stored recipient differs from the configured reviewer.")
            previous = await store.get_item(key)
            if previous:
                if previous.value["state"] in {"notified", "opened"}:
                    return {"event_id": key, "state": previous.value["state"], "duplicate": True}
                raise ValueError("This commit already has an incomplete/failed attempt; inspect it, do not auto-retry.")
            latest = await store.get_item("latest")
            if latest and request.build_id <= latest.value["build_id"]:
                raise ValueError("A newer build has already been accepted; this event is stale.")
            record: dict[str, Any] = {
                "event_id": key, "request": request.model_dump(mode="json"),
                "recipient": recipient.model_dump(mode="json"), "state": "assessing",
                "policy_hash": canonical_hash(self.policy.model_dump(mode="json")),
                "created_at": datetime.now(UTC).isoformat(),
            }
            try:
                claimed = await store.create_item(key, record)
            except FoundryStorageConflictError:
                raise ValueError("This commit is already being processed; duplicate refused.") from None
            # New accepted events invalidate older review cards. Store updates
            # are conditional; overlapping pipeline deliveries fail closed.
            pointer: dict[str, Any] = {"event_id": key, "build_id": request.build_id}
            if latest:
                await store.set_item("latest", pointer, if_match=latest.etag)
            else:
                await store.create_item("latest", pointer)
            assessment = AgentRequest.model_validate({
                "contract_version": "1.0.0", "request_id": key, "correlation_id": str(uuid4()),
                "trigger": "azure_repos_main_push", "requested_by": f"pipeline:{request.pipeline_id}",
                "subject": {
                    "repo": self.policy.repository_url, "commit_sha": request.commit_sha,
                    "changed_paths": self.policy.source_paths,
                },
                "context": {"wiki_page_paths": [self.policy.wiki_page], "work_item_ids": self.policy.work_item_ids},
                "documentation_standard_ref": self.policy.documentation_standard_ref,
                "task": {
                    "scope": "information_review",
                    "question": (
                        "Review the implementation snapshot in the listed source files at the exact commit against "
                        "the documentation standard and the requested current wiki. These are the configured review "
                        "files, not a claim that every file changed in this push. Identify documentation gaps, propose "
                        "updates only for the requested wiki page and report facts that cannot be established. "
                        "Never write or claim that a proposal has been approved."
                    ),
                },
            })
            try:
                result = await self.assessor.assess(assessment)
                if result.request_id != assessment.request_id:
                    raise ValueError("Assessment result belongs to another event.")
                if any(e.source == "git" and e.version != request.commit_sha for e in result.evidence):
                    raise ValueError("Assessment evidence does not match the pushed commit.")
                if any(p.target_page != self.policy.wiki_page for p in result.proposed_changes):
                    raise ValueError("Assessment proposed an unexpected wiki target.")
                record.update(result=result.model_dump(mode="json"), state="ready")
                claimed = await store.set_item(key, record, if_match=claimed.etag)
            except Exception as exc:
                LOGGER.error("Push assessment %s failed (%s).", key, type(exc).__name__)
                record.update(state="assessment_failed", error_type=type(exc).__name__)
                await store.set_item(key, record, if_match=claimed.etag)
                raise
            current = await store.get_item("latest")
            if current is None or current.value != pointer:
                raise ValueError("This assessment was superseded; no notification sent.")
            notification = card([
                text("Documentation review ready", weight="Bolder", size="Medium"),
                text(f"Repository: {self.policy.repository_url}"),
                text(f"Main commit: {request.commit_sha}"),
                text(f"Status: {result.documentation_status}"),
                text(f"{len(result.findings)} findings; {len(result.missing_information)} missing-information items."),
                text(
                    "Review the findings in this chat. Any approved write replaces only the sandbox review report, "
                    "not the integration wiki. No write has been authorized."
                ),
            ], [{
                "type": "Action.Submit", "title": "Open review", "associatedInputs": "none",
                "data": {"interface_version": "1.0.0", "action": "review_push", "event_id": key},
            }])
            # Claim before delivery: a timeout may have delivered a card. Do not
            # automatically post it twice. Reviewer can use 'review <event-id>'.
            record["state"] = "notifying"
            claimed = await store.set_item(key, record, if_match=claimed.etag)
            try:
                await self.notify(ConversationReference.model_validate(recipient.reference), notification)
            except Exception as exc:
                LOGGER.error("Push notification %s uncertain (%s); no automatic retry.", key, type(exc).__name__)
                record.update(state="notification_unknown", error_type=type(exc).__name__)
                await store.set_item(key, record, if_match=claimed.etag)
                raise
            record["state"] = "notified"
            await store.set_item(key, record, if_match=claimed.etag)
            return {"event_id": key, "state": "notified", "duplicate": False}

    async def open_review(self, activity: Activity, event_id: UUID) -> dict[str, Any]:
        binding = self.reviewer(activity)
        store = await self.store()
        async with store:
            item = await store.get_item(str(event_id))
            latest = await store.get_item("latest")
            if item is None or latest is None or latest.value["event_id"] != str(event_id):
                raise ValueError("Review is unavailable or superseded by a newer push.")
            record = item.value
            if record["policy_hash"] != canonical_hash(self.policy.model_dump(mode="json")):
                raise ValueError("Automation policy changed; this stored review is no longer eligible.")
            recipient = Recipient.model_validate(record["recipient"])
            # Allow a fresh platform session, but not a different person/chat.
            expected = recipient.binding
            if (
                binding.owner != expected.owner or binding.aad_object_id != expected.aad_object_id
                or binding.tenant_id != expected.tenant_id or binding.conversation_id != expected.conversation_id
            ):
                raise ValueError("Review belongs to another reviewer or conversation.")
            if record["state"] == "opened":
                await self.teams.check_binding(UUID(record["pending_id"]), binding)
                pending = await self.teams.record(UUID(record["pending_id"]), binding)
                return review_card(pending, self.teams.agent.policy.content_parameter)
            if record["state"] not in {"notified", "notification_unknown", "notifying"}:
                raise ValueError("Review is not ready or was already claimed; inspect status before retrying.")
            result = AgentResult.model_validate(record["result"])
            if not result.proposed_changes:
                return card([
                    text("Assessment completed without a write proposal", weight="Bolder"),
                    text(f"Status: {result.documentation_status}"),
                    *[text(f.description) for f in result.findings],
                    *[text(m.description) for m in result.missing_information],
                ])
            proposal = ProposeCall(
                action="propose", run_id=result.request_id, content=report_content(result), evidence=result.evidence,
            )
            record["state"] = "opening"
            claimed = await store.set_item(str(event_id), record, if_match=item.etag)
            try:
                output = await self.teams.agent.execute(
                    proposal.model_dump_json(), AgentSession(session_id=binding.platform_session_id),
                )
                approval = next(c for c in output if c.type == "function_approval_request")
                pending = await self.teams.record(UUID(approval.id or ""), binding)
                await store.create_item(f"pending:{pending.pending_id}", {"event_id": str(event_id)})
                await self.teams.save_binding(pending, binding)
                record.update(state="opened", pending_id=str(pending.pending_id))
                await store.set_item(str(event_id), record, if_match=claimed.etag)
                return review_card(pending, self.teams.agent.policy.content_parameter)
            except Exception as exc:
                LOGGER.error("Opening push review %s failed (%s); no automatic retry.", event_id, type(exc).__name__)
                raise

    async def require_current(self, pending_id: UUID) -> None:
        store = await self.store()
        async with store:
            event = await store.get_item(f"pending:{pending_id}")
            if event:
                latest = await store.get_item("latest")
                if latest is None or latest.value["event_id"] != event.value["event_id"]:
                    raise ValueError("This proposal was superseded by a newer push; open the latest review.")
                assessment = await store.get_item(event.value["event_id"])
                if (
                    assessment is None
                    or assessment.value["policy_hash"] != canonical_hash(self.policy.model_dump(mode="json"))
                ):
                    raise ValueError("Automation policy changed; this stored proposal is no longer eligible.")

    async def inherit_event(self, previous: UUID, replacement: UUID) -> None:
        store = await self.store()
        async with store:
            event = await store.get_item(f"pending:{previous}")
            if event:
                await store.create_item(f"pending:{replacement}", event.value)
