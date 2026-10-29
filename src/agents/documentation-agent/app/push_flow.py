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

from contracts.drafts import DraftPublished, PreparedDraft, VerifiedDraft, content_hash, draft_url, pull_request_url
from contracts.models import CommitSha, ContractModel, NonBlank
from contracts.repositories import azure_repository
from contracts.v1 import AgentRequest, AgentResult
from contracts.wiki import WikiDraftBundle, WikiSnapshot

from .approval import PendingCall, ProposeCall, WikiRead
from .approval_common import canonical_hash
from .channel_policy import SharedReviewScope
from .channel_reviews import MemberCheck
from .conversation import ConversationService
from .teams import ChannelBinding, TeamsApproval
from .teams_card import card, linked_review_card, review_card, status_header, text
from .wiki_drafts import WikiDraftPublisher

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
    merged_pr_drafts: bool = False
    compose_wiki_page: bool = False
    draft_storage: Literal["git_branch", "wiki"] = "git_branch"

    @model_validator(mode="after")
    def valid_sources(self) -> Self:
        if self.compose_wiki_page and not self.merged_pr_drafts:
            raise ValueError("Real wiki page composition requires the merged-PR draft flow.")
        if self.draft_storage == "wiki" and not self.compose_wiki_page:
            raise ValueError("Wiki drafts require complete-page composition.")
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

    @property
    def write_target(self) -> str:
        return self.wiki_page if self.compose_wiki_page else self.sandbox_page

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
    pull_request_id: Annotated[int, Field(strict=True, gt=0)] | None = None


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


class Notify(Protocol):
    async def __call__(
        self, reference: ConversationReference, output: dict[str, Any],
        channel_scope: SharedReviewScope | None = None,
    ) -> SharedReviewScope | None: ...
ReadDraft = Callable[[str, UUID, str], Awaitable[str]]


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
    def __init__(
        self, policy: PushPolicy, teams: TeamsApproval, assessor: Assessment, notify: Notify,
        read_draft: ReadDraft | None = None,
        read_notes: ReadDraft | None = None,
        read_wiki: WikiRead | None = None,
        wiki_publisher: WikiDraftPublisher | None = None,
    ) -> None:
        self.policy = policy
        self.teams = teams
        self.assessor = assessor
        self.notify = notify
        self.read_draft = read_draft
        self.read_notes = read_notes
        self.read_wiki = read_wiki
        self.wiki_publisher = wiki_publisher
        if teams.channels is not None and policy.draft_storage != "wiki":
            raise ValueError("Shared channel reviews require the complete-page wiki draft flow.")
        if policy.merged_pr_drafts and policy.draft_storage == "git_branch" and read_draft is None:
            raise ValueError("Merged-PR drafts require a commit-pinned draft reader.")
        if teams.agent.policy.fixed_arguments.get("path") != policy.write_target:
            raise ValueError("Approval target does not match the operator's explicit push-flow target.")
        if policy.compose_wiki_page and (
            read_wiki is None or teams.agent.policy.wiki_etag_parameter != "etag"
            or (policy.draft_storage == "git_branch" and read_notes is None)
        ):
            raise ValueError("Real page updates require snapshot/notes readers and conditional ETag approval.")
        if policy.draft_storage == "wiki" and (
            wiki_publisher is None or teams.agent.policy.review_draft_prefix != "/Drafts/Order Sync"
        ):
            raise ValueError("Wiki drafts require a prefix-restricted publisher and draft-bound approval policy.")

    async def store(self) -> FoundryStateStore:
        # Pipeline and reviewer need different identities. Access to this shared
        # inbox is mediated below, never by client-selected store keys or owners.
        return await FoundryStateStore.get_or_create(STORE, user_isolation=False)

    def reviewer(self, activity: Activity) -> ChannelBinding:
        binding = self.teams.binding(activity)
        if binding.shared_scope is not None and self.teams.channels is not None:
            self.teams.channels.authorize(binding)
            return binding
        if binding.aad_object_id != self.policy.reviewer_aad_id:
            raise ValueError("Only the configured reviewer can register or open push reviews.")
        return binding

    async def register(self, activity: Activity, *, member_check: MemberCheck | None = None) -> dict[str, Any]:
        binding = self.reviewer(activity)
        if self.teams.channels is not None:
            await self.teams.channels.verify_decision(binding, None, member_check)
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
            existing = await store.get_item(self.recipient_key())
            if existing is None:
                await store.create_item(self.recipient_key(), recipient.model_dump(mode="json"))
            else:
                await store.set_item(self.recipient_key(), recipient.model_dump(mode="json"), if_match=existing.etag)
        return card([
            text("Repository notifications connected", weight="Bolder", size="Medium"),
            text(f"Repository: {self.policy.repository_url}"),
            text(
                "Merged pull requests will create review threads in this channel."
                if binding.shared_scope else
                "Merged pull requests will be assessed; draft links will be sent to this personal chat."
                if self.policy.merged_pr_drafts else
                "Main-branch changes will be assessed and sent to this personal chat."
            ),
            text(
                "Reviewers share one proposal per thread. The configured reviewer rule is checked on every decision. "
                "Automation never approves a write."
                if binding.shared_scope else
                "Opening a review creates a new approval in your session. Automation never approves a write."
            ),
        ])

    def recipient_key(self) -> str:
        channels = self.teams.channels
        if channels is None:
            return "recipient"
        return "channel-recipient:" + canonical_hash({
            "tenant": str(channels.policy.tenant_id), "team": channels.policy.team_id,
            "team_aad_group_id": str(channels.policy.team_aad_group_id),
            "channel": channels.policy.channel_id,
        })

    async def deliver(self, store: FoundryStateStore, record: dict[str, Any], output: dict[str, Any]) -> None:
        recipient = Recipient.model_validate(record["recipient"])
        reference = ConversationReference.model_validate(recipient.reference)
        scope = (
            await self.notify(reference, output, recipient.binding.shared_scope)
            if recipient.binding.shared_scope is not None else await self.notify(reference, output)
        )
        if recipient.binding.shared_scope is not None:
            channels = self.teams.channels
            if channels is None or not isinstance(scope, SharedReviewScope):
                raise ValueError("Channel delivery did not return a verified review thread.")
            channels.policy.require_scope(scope)
            record["shared_scope"] = scope.model_dump(mode="json")
            await store.create_item("thread:" + canonical_hash(scope.model_dump(mode="json")), {
                "event_id": record["event_id"],
            })

    async def channel_conversation(
        self, binding: ChannelBinding, conversation: ConversationService,
    ) -> ConversationService:
        if self.teams.channels is None or binding.shared_scope is None:
            raise ValueError("Channel discussion requires a configured scope.")
        self.teams.channels.authorize(binding)
        store = await self.store()
        async with store:
            mapping = await store.get_item("thread:" + canonical_hash(binding.shared_scope.model_dump(mode="json")))
            if mapping is None:
                return conversation
            item = await store.get_item(mapping.value["event_id"])
            if (
                item is None or item.value.get("shared_scope") != binding.shared_scope.model_dump(mode="json")
                or item.value["policy_hash"] != canonical_hash(self.policy.model_dump(mode="json"))
            ):
                raise ValueError("This thread's review context is unavailable or its policy changed.")
            sources = conversation.sources.model_copy(deep=True)
            sources.subject.commit_sha = item.value["request"]["commit_sha"]
            bundle = WikiDraftBundle.model_validate(item.value["wiki_draft"])
            for snapshot in (bundle.page, bundle.notes):
                if snapshot is not None and snapshot.path not in sources.context.wiki_page_paths:
                    sources.context.wiki_page_paths.append(snapshot.path)
            return ConversationService(conversation.settings, sources, conversation.runner)

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
        if self.policy.merged_pr_drafts and request.pull_request_id is None:
            raise ValueError("This flow accepts only a pipeline-verified completed pull request.")
        if not self.policy.merged_pr_drafts and request.pull_request_id is not None:
            raise ValueError("Merged-PR delivery is not enabled on this version.")
        key = event_key(self.policy, request.commit_sha)
        store = await self.store()
        async with store:
            subscriber = await store.get_item(self.recipient_key())
            if subscriber is None:
                raise ValueError(
                    "Reviewer must enable notifications ('connect repo') in the configured Teams destination first."
                )
            recipient = Recipient.model_validate(subscriber.value)
            if self.teams.channels is not None:
                self.teams.channels.authorize(recipient.binding, decide=True)
            elif (
                recipient.binding.shared_scope is not None
                or recipient.binding.aad_object_id != self.policy.reviewer_aad_id
            ):
                raise ValueError("Stored recipient differs from the configured reviewer.")
            previous = await store.get_item(key)
            if previous:
                if previous.value["policy_hash"] != canonical_hash(self.policy.model_dump(mode="json")):
                    raise ValueError("Stored event uses a different policy; do not reuse it.")
                if previous.value["request"].get("pull_request_id") != request.pull_request_id:
                    raise ValueError("Commit was already associated with a different pull request.")
                if (
                    self.policy.merged_pr_drafts and self.policy.draft_storage == "git_branch"
                    and previous.value["state"] == "draft_ready"
                ):
                    return self.prepared_draft(previous.value, duplicate=True)
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
                "trigger": "azure_repos_pr_merged" if self.policy.merged_pr_drafts else "azure_repos_main_push",
                "requested_by": f"pipeline:{request.pipeline_id}",
                "subject": {
                    "repo": self.policy.repository_url, "commit_sha": request.commit_sha,
                    "changed_paths": self.policy.source_paths,
                    **(
                        {"pr_reference": pull_request_url(self.policy.repository_url, request.pull_request_id)}
                        if request.pull_request_id is not None else {}
                    ),
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
                snapshot = None
                if self.policy.compose_wiki_page:
                    if self.read_wiki is None:
                        raise ValueError("Wiki snapshot reader is unavailable.")
                    snapshot = await self.read_wiki(self.policy.wiki_page)
                    if snapshot.path != self.policy.wiki_page:
                        raise ValueError("Wiki snapshot targets another page.")
                    if assessment.task is None:
                        raise ValueError("Page composition requires an explicit assessment task.")
                    assessment.task.question += (
                        " Each proposed change must target one plain H2 section heading on the requested page. "
                        "Supply final documentation text for that section, not instructions to an editor. "
                        "Do not rewrite the page title or unrelated sections. Use explicit Information missing "
                        "placeholders for requested facts not supported by sources."
                    )
                result = await self.assessor.assess(assessment)
                if result.request_id != assessment.request_id:
                    raise ValueError("Assessment result belongs to another event.")
                if any(e.source == "git" and e.version != request.commit_sha for e in result.evidence):
                    raise ValueError("Assessment evidence does not match the pushed commit.")
                if any(p.target_page != self.policy.wiki_page for p in result.proposed_changes):
                    raise ValueError("Assessment proposed an unexpected wiki target.")
                if snapshot is not None:
                    if self.read_wiki is None:
                        raise ValueError("Wiki snapshot reader is unavailable.")
                    after = await self.read_wiki(self.policy.wiki_page)
                    if after != snapshot:
                        raise ValueError("Wiki changed during assessment; generate a fresh draft.")
                    wiki_evidence = [item for item in result.evidence if item.source == "wiki"]
                    if not wiki_evidence or any(
                        item.version.strip('"') != snapshot.etag.strip('"') for item in wiki_evidence
                    ):
                        raise ValueError("Assessment wiki evidence does not match the captured page version.")
                    record["wiki_base"] = snapshot.model_dump(mode="json")
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
            if self.policy.merged_pr_drafts:
                # Validate write limits before handing a draft to the pipeline.
                # The exact same bytes will later become the pending arguments.
                if self.policy.compose_wiki_page:
                    from .wiki_page import compose_page, review_notes

                    base = WikiSnapshot.model_validate(record["wiki_base"])
                    content = compose_page(base, result)
                    record["review_notes"] = review_notes(base, content, result)
                else:
                    content = report_content(result)
                if result.proposed_changes:
                    ProposeCall(
                        action="propose", run_id=result.request_id, content=content, evidence=result.evidence,
                        expected_wiki_etag=record.get("wiki_base", {}).get("etag"),
                    )
                record.update(state="draft_ready", draft_content=content)
                prepared = self.prepared_draft(record, duplicate=False)
                claimed = await store.set_item(key, record, if_match=claimed.etag)
                if self.policy.draft_storage == "wiki":
                    return await self.publish_wiki_draft(store, record, claimed.etag)
                return prepared
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
                await self.deliver(store, record, notification)
            except Exception as exc:
                LOGGER.error("Push notification %s uncertain (%s); no automatic retry.", key, type(exc).__name__)
                record.update(state="notification_unknown", error_type=type(exc).__name__)
                await store.set_item(key, record, if_match=claimed.etag)
                raise
            record["state"] = "notified"
            await store.set_item(key, record, if_match=claimed.etag)
            return {"event_id": key, "state": "notified", "duplicate": False}

    @staticmethod
    def prepared_draft(record: dict[str, Any], *, duplicate: bool) -> dict[str, Any]:
        return PreparedDraft(
            event_id=record["event_id"], state="draft_ready", duplicate=duplicate,
            content=record["draft_content"], content_sha256=content_hash(record["draft_content"]),
            source_commit=record["request"]["commit_sha"], pull_request_id=record["request"]["pull_request_id"],
            review_notes=record.get("review_notes"),
        ).model_dump(mode="json")

    async def publish_wiki_draft(
        self, store: FoundryStateStore, record: dict[str, Any], etag: str,
    ) -> dict[str, Any]:
        if self.wiki_publisher is None:
            raise ValueError("Wiki draft publisher is not configured.")
        key = record["event_id"]
        record["state"] = "draft_publishing"
        claimed = await store.set_item(key, record, if_match=etag)
        try:
            bundle = await self.wiki_publisher.publish(
                UUID(key), record["request"]["pull_request_id"], record["draft_content"], record.get("review_notes"),
            )
        except Exception as exc:
            LOGGER.error("Wiki draft publication %s uncertain (%s); no automatic retry.", key, type(exc).__name__)
            record.update(state="draft_publication_unknown", error_type=type(exc).__name__)
            await store.set_item(key, record, if_match=claimed.etag)
            raise
        record["wiki_draft"] = bundle.model_dump(mode="json")
        latest = await store.get_item("latest")
        if latest is None or latest.value["event_id"] != key:
            record["state"] = "superseded"
            await store.set_item(key, record, if_match=claimed.etag)
            raise ValueError("Assessment was superseded while creating the draft; no notification sent.")
        return await self.notify_wiki_draft(store, record, claimed.etag)

    async def notify_wiki_draft(
        self, store: FoundryStateStore, record: dict[str, Any], etag: str,
    ) -> dict[str, Any]:
        key = record["event_id"]
        bundle = WikiDraftBundle.model_validate(record["wiki_draft"])
        result = AgentResult.model_validate(record["result"])
        notification = card([
            status_header("pending", title="Documentation draft ready"),
            text(f"Merged PR #{record['request']['pull_request_id']}"),
            text(f"Findings: {len(result.findings)}; missing facts: {len(result.missing_information)}."),
            text(f"Publish target: {self.policy.write_target}. The published page has not changed."),
        ], [
            {"type": "Action.OpenUrl", "title": "Draft page", "url": bundle.page.uri},
            {"type": "Action.OpenUrl", "title": "Changes",
             "url": bundle.notes.uri if bundle.notes else bundle.page.uri},
            {"type": "Action.Submit", "title": "Review", "associatedInputs": "none",
             "data": {"interface_version": "1.0.0", "action": "review_push", "event_id": key}},
        ])
        record["state"] = "notifying"
        claimed = await store.set_item(key, record, if_match=etag)
        try:
            await self.deliver(store, record, notification)
        except Exception as exc:
            LOGGER.error("Wiki draft notification %s uncertain (%s); no automatic retry.", key, type(exc).__name__)
            record.update(state="notification_unknown", error_type=type(exc).__name__)
            await store.set_item(key, record, if_match=claimed.etag)
            raise
        record["state"] = "notified"
        await store.set_item(key, record, if_match=claimed.etag)
        return {"event_id": key, "state": "notified", "duplicate": False}

    async def retry_channel_notification(
        self, activity: Activity, event_id: UUID, *, member_check: MemberCheck | None = None,
    ) -> dict[str, Any]:
        """One human-requested delivery retry, never a rerun of assessment or writes."""
        binding = self.reviewer(activity)
        channels = self.teams.channels
        if channels is None or binding.shared_scope is None or self.read_wiki is None:
            raise ValueError("Retry requires a verified channel and wiki draft reader.")
        await channels.verify_decision(binding, None, member_check)
        store = await self.store()
        async with store:
            item = await store.get_item(str(event_id))
            latest = await store.get_item("latest")
            if item is None or latest is None or latest.value["event_id"] != str(event_id):
                raise ValueError("Notification event is unknown or superseded.")
            record = item.value
            expected = Recipient.model_validate(record["recipient"]).binding.shared_scope
            if expected is None or (
                expected.tenant_id, expected.team_id, expected.channel_id, expected.team_aad_group_id
            ) != (
                binding.shared_scope.tenant_id, binding.shared_scope.team_id,
                binding.shared_scope.channel_id, binding.shared_scope.team_aad_group_id,
            ):
                raise ValueError("Notification belongs to another destination.")
            if (
                record["policy_hash"] != canonical_hash(self.policy.model_dump(mode="json"))
                or record["state"] != "notification_unknown" or record.get("shared_scope")
                or record.get("notification_retry") or not record.get("wiki_draft")
            ):
                raise ValueError("Event is not eligible for a single notification retry; inspect its saved outcome.")
            bundle = WikiDraftBundle.model_validate(record["wiki_draft"])
            for snapshot in (bundle.page, bundle.notes):
                if snapshot is not None and await self.read_wiki(snapshot.path) != snapshot:
                    raise ValueError("Draft or notes changed; cannot retry this notification.")
            if await self.read_wiki(self.policy.wiki_page) != WikiSnapshot.model_validate(record["wiki_base"]):
                raise ValueError("Published page changed; cannot retry this old draft.")
            await channels.verify_decision(binding, None, member_check)
            # CAS before dispatch consumes the one explicit retry even if delivery
            # is interrupted. Repeated commands never replay a side effect.
            record["notification_retry"] = {
                "requested_by": binding.owner, "aad_id": str(binding.aad_object_id),
                "requested_at": datetime.now(UTC).isoformat(),
            }
            record["state"] = "notification_retrying"
            claimed = await self.teams.agent.replace(store, str(event_id), record, item.etag)
            await self.notify_wiki_draft(store, record, claimed.etag)
        return card([text("Review notification posted", weight="Bolder"),
                     text("Open the new review post. No wiki publication has been approved.")])

    async def publish_draft(self, published: DraftPublished) -> dict[str, Any]:
        self.require_caller()
        if not self.policy.merged_pr_drafts or self.policy.draft_storage != "git_branch" or self.read_draft is None:
            raise ValueError("Draft publication is not enabled.")
        key = str(published.event_id)
        store = await self.store()
        async with store:
            item = await store.get_item(key)
            latest = await store.get_item("latest")
            if item is None or latest is None or latest.value["event_id"] != key:
                raise ValueError("Draft event is unknown or superseded.")
            record = item.value
            if record["policy_hash"] != canonical_hash(self.policy.model_dump(mode="json")):
                raise ValueError("Draft policy changed.")
            if record["state"] in {"notified", "opened"}:
                if record.get("draft", {}).get("commit") != published.draft_commit:
                    raise ValueError("Cannot replace the draft behind an existing approval.")
                return {"event_id": key, "state": record["state"], "duplicate": True}
            if record["state"] != "draft_ready":
                raise ValueError("Draft is not ready; inspect uncertain delivery before retrying.")
            actual = await self.read_draft(self.policy.repository_url, published.event_id, published.draft_commit)
            if actual != record["draft_content"]:
                raise ValueError("Published draft bytes differ from the saved proposal; no notification sent.")
            if record.get("review_notes") is not None:
                if self.read_notes is None:
                    raise ValueError("Review notes reader is unavailable.")
                notes = await self.read_notes(self.policy.repository_url, published.event_id, published.draft_commit)
                if notes != record["review_notes"]:
                    raise ValueError("Published review notes differ from the saved diff/evidence.")
            verified = VerifiedDraft(commit=published.draft_commit, content_sha256=content_hash(actual))
            record["draft"] = verified.model_dump(mode="json")
            result = AgentResult.model_validate(record["result"])
            notification = card([
                text("Documentation draft ready", weight="Bolder", size="Medium"),
                text(f"Merged PR #{record['request']['pull_request_id']}"),
                text(f"Findings: {len(result.findings)}; missing facts: {len(result.missing_information)}."),
                text(f"Approval target: {self.policy.write_target}"),
                text("Draft only. The live integration wiki is unchanged."),
            ], [
                {"type": "Action.OpenUrl", "title": "View draft",
                 "url": draft_url(self.policy.repository_url, published.event_id, published.draft_commit)},
                {"type": "Action.OpenUrl", "title": "Merged PR",
                 "url": pull_request_url(self.policy.repository_url, record["request"]["pull_request_id"])},
                {"type": "Action.Submit", "title": "Review decision", "associatedInputs": "none",
                 "data": {"interface_version": "1.0.0", "action": "review_push", "event_id": key}},
            ])
            if record.get("review_notes") is not None:
                notification["body"].append({"type": "ActionSet", "actions": [{
                    "type": "Action.OpenUrl", "title": "Changes & evidence",
                    "url": draft_url(
                        self.policy.repository_url, published.event_id, published.draft_commit, review=True
                    ),
                }]})
                notification = card(notification["body"], notification["actions"])
            # The read may have taken time; do not knowingly notify an older event.
            latest = await store.get_item("latest")
            if latest is None or latest.value["event_id"] != key:
                raise ValueError("Draft was superseded during verification.")
            record["state"] = "notifying"
            claimed = await store.set_item(key, record, if_match=item.etag)
            try:
                await self.deliver(store, record, notification)
            except Exception as exc:
                LOGGER.error("Draft notification %s uncertain (%s); do not resend blindly.", key, type(exc).__name__)
                record.update(state="notification_unknown", error_type=type(exc).__name__)
                await store.set_item(key, record, if_match=claimed.etag)
                raise
            record["state"] = "notified"
            await store.set_item(key, record, if_match=claimed.etag)
            return {"event_id": key, "state": "notified", "duplicate": False}

    def render_review(self, pending: PendingCall, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("wiki_draft"):
            bundle = WikiDraftBundle.model_validate(record["wiki_draft"])
            result = AgentResult.model_validate(record["result"])
            return linked_review_card(
                pending, bundle.page.uri,
                pull_request_url(self.policy.repository_url, record["request"]["pull_request_id"]),
                self.policy.write_target, len(result.findings), len(result.missing_information),
                matches_draft=pending.arguments[self.teams.agent.policy.content_parameter] == bundle.page.content,
                page_update=True, notes_link=bundle.notes.uri if bundle.notes else None, wiki_draft=True,
            )
        if not record.get("draft"):
            return review_card(pending, self.teams.agent.policy.content_parameter)
        draft = VerifiedDraft.model_validate(record["draft"])
        content = pending.arguments[self.teams.agent.policy.content_parameter]
        if not isinstance(content, str):
            raise ValueError("Pending content is not text.")
        result = AgentResult.model_validate(record["result"])
        return linked_review_card(
            pending,
            draft_url(self.policy.repository_url, UUID(record["event_id"]), draft.commit),
            pull_request_url(self.policy.repository_url, record["request"]["pull_request_id"]),
            self.policy.write_target, len(result.findings), len(result.missing_information),
            matches_draft=content_hash(content) == draft.content_sha256,
            page_update=self.policy.compose_wiki_page,
            notes_link=(
                draft_url(self.policy.repository_url, UUID(record["event_id"]), draft.commit, review=True)
                if record.get("review_notes") is not None else None
            ),
        )

    async def render_pending(self, pending: PendingCall) -> dict[str, Any]:
        store = await self.store()
        async with store:
            lineage = await store.get_item(f"pending:{pending.pending_id}")
            if lineage is None:
                return review_card(pending, self.teams.agent.policy.content_parameter)
            record = await store.get_item(lineage.value["event_id"])
            if record is None:
                raise ValueError("Proposal origin is unavailable; cannot render draft review.")
            values = {**record.value}
            if lineage.value.get("wiki_draft"):
                values["wiki_draft"] = lineage.value["wiki_draft"]
            return self.render_review(pending, values)

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
            if binding.shared_scope is not None:
                if record.get("shared_scope") != binding.shared_scope.model_dump(mode="json"):
                    raise ValueError("Review belongs to another channel or thread.")
            elif expected.shared_scope is not None or (
                binding.owner != expected.owner or binding.aad_object_id != expected.aad_object_id
                or binding.tenant_id != expected.tenant_id or binding.conversation_id != expected.conversation_id
            ):
                raise ValueError("Review belongs to another reviewer or conversation.")
            if record["state"] == "opened":
                await self.teams.check_binding(UUID(record["pending_id"]), binding)
                pending = await self.teams.record(UUID(record["pending_id"]), binding)
                if binding.shared_scope is not None and self.teams.channels is not None:
                    return await self.teams.channels.render(pending, binding)
                return await self.render_pending(pending)
            if record["state"] not in {"notified", "notification_unknown", "notifying"}:
                raise ValueError("Review is not ready or was already claimed; inspect status before retrying.")
            result = AgentResult.model_validate(record["result"])
            if not result.proposed_changes:
                if record.get("wiki_draft"):
                    return card([
                        text("Review completed - no write proposed", weight="Bolder"),
                        text("The published page is unchanged. Read the findings in the draft review."),
                    ], [{"type": "Action.OpenUrl", "title": "View findings",
                         "url": record["wiki_draft"]["notes"]["uri"] if record["wiki_draft"].get("notes")
                         else record["wiki_draft"]["page"]["uri"]}])
                if record.get("draft"):
                    return card([
                        text("Review completed - no write proposed", weight="Bolder", size="Medium"),
                        text(f"Status: {result.documentation_status}. Read the findings in the draft."),
                    ], [{"type": "Action.OpenUrl", "title": "View findings",
                         "url": draft_url(self.policy.repository_url, event_id, record["draft"]["commit"])}])
                return card([
                    text("Assessment completed without a write proposal", weight="Bolder"),
                    text(f"Status: {result.documentation_status}"),
                    *[text(f.description) for f in result.findings],
                    *[text(m.description) for m in result.missing_information],
                ])
            proposal = ProposeCall(
                action="propose", run_id=result.request_id,
                content=(
                    record["draft_content"]
                    if record.get("draft") or record.get("wiki_draft") else report_content(result)
                ),
                evidence=result.evidence,
                expected_wiki_etag=record.get("wiki_base", {}).get("etag"),
                review_draft=(
                    WikiSnapshot.model_validate(record["wiki_draft"]["page"]) if record.get("wiki_draft") else None
                ),
                review_notes=(
                    WikiSnapshot.model_validate(record["wiki_draft"]["notes"])
                    if record.get("wiki_draft", {}).get("notes") else None
                ),
            )
            record["state"] = "opening"
            claimed = await store.set_item(str(event_id), record, if_match=item.etag)
            try:
                if binding.shared_scope is not None and self.teams.channels is not None:
                    pending = await self.teams.channels.create(proposal, binding)
                else:
                    output = await self.teams.agent.execute(
                        proposal.model_dump_json(), AgentSession(session_id=binding.platform_session_id),
                    )
                    approval = next(c for c in output if c.type == "function_approval_request")
                    pending = await self.teams.record(UUID(approval.id or ""), binding)
                await store.create_item(f"pending:{pending.pending_id}", {"event_id": str(event_id)})
                await self.teams.save_binding(pending, binding)
                record.update(state="opened", pending_id=str(pending.pending_id))
                await store.set_item(str(event_id), record, if_match=claimed.etag)
                if binding.shared_scope is not None and self.teams.channels is not None:
                    return await self.teams.channels.render(pending, binding)
                return self.render_review(pending, record)
            except Exception as exc:
                LOGGER.error("Opening push review %s failed (%s); no automatic retry.", event_id, type(exc).__name__)
                raise

    async def require_current(self, pending_id: UUID, *, required: bool = False) -> None:
        store = await self.store()
        async with store:
            event = await store.get_item(f"pending:{pending_id}")
            if required and event is None:
                raise ValueError("Shared approval has no completed automation handoff; inspect before deciding.")
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

    async def revision_draft(self, pending: PendingCall, content: str) -> WikiDraftBundle | None:
        if self.policy.draft_storage != "wiki":
            return None
        store = await self.store()
        async with store:
            mapping = await store.get_item(f"pending:{pending.pending_id}")
            if mapping is None:
                raise ValueError("Wiki draft revision requires an existing automation review.")
            event = await store.get_item(mapping.value["event_id"])
            if event is None or self.wiki_publisher is None:
                raise ValueError("Original review is unavailable.")
            from .wiki_page import review_notes

            base = WikiSnapshot.model_validate(event.value["wiki_base"])
            result = AgentResult.model_validate(event.value["result"])
            notes = "# Reviewer-edited revision\n\n" + review_notes(base, content, result)
            return await self.wiki_publisher.publish(
                UUID(event.value["event_id"]), event.value["request"]["pull_request_id"],
                content, notes, revision_id=uuid4(),
            )

    async def inherit_event(
        self, previous: UUID, replacement: UUID, bundle: WikiDraftBundle | None = None,
    ) -> None:
        store = await self.store()
        async with store:
            event = await store.get_item(f"pending:{previous}")
            if event:
                values = {**event.value}
                if bundle is not None:
                    values["wiki_draft"] = bundle.model_dump(mode="json")
                await store.create_item(f"pending:{replacement}", values)
                original = await store.get_item(event.value["event_id"])
                if original is not None and original.value.get("pending_id") == str(previous):
                    await store.set_item(
                        event.value["event_id"], {
                            **original.value, "pending_id": str(replacement),
                            **({"wiki_draft": bundle.model_dump(mode="json")} if bundle is not None else {}),
                        },
                        if_match=original.etag,
                    )
