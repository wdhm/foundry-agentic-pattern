"""Opt-in exact-call approval runtime. Assessment remains read-only."""

import argparse
import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, Self
from uuid import UUID, uuid4

from agent_framework import AgentRunInputs, AgentSession, Content
from agent_framework_foundry_hosting import FoundryToolbox, ResponsesHostServer
from azure.ai.agentserver.core.storage import FoundryStateStore
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.types import PaginatedRequestParams, Tool
from pydantic import Field, JsonValue, TypeAdapter, ValidationError, model_validator

from contracts.models import ContractModel, NonBlank
from contracts.v1 import AgentResult, Evidence, Provenance
from contracts.wiki import WikiETag, WikiSnapshot

from .agent import request_text
from .approval_common import ApprovalAgentBase, approval_decision, canonical_hash

LOGGER = logging.getLogger(__name__)
STORE_NAME = "documentation-tool-approvals-v1"
Text = Annotated[NonBlank, Field(max_length=16000)]


class ToolApprovalPolicy(ContractModel):
    """Operator-owned target; callers can change only the proposed text."""

    toolbox_endpoint: NonBlank
    tool_name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+___[A-Za-z0-9_-]+$")]
    fixed_arguments: Annotated[dict[str, JsonValue], Field(min_length=1)]
    content_parameter: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
    proposal_page_parameter: NonBlank | None = None
    proposal_section_parameter: NonBlank | None = None
    wiki_etag_parameter: Literal["etag"] | None = None
    review_draft_prefix: Literal["/Drafts/Order Sync"] | None = None
    auth_mode: Literal["managed_identity", "azure_cli"] = "managed_identity"
    timeout_seconds: int = Field(default=60, gt=0, le=180)
    approval_ttl_seconds: int = Field(default=3600, gt=0, le=86400)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if not re.fullmatch(
            r"https://[a-z0-9-]+\.services\.ai\.azure\.com/api/projects/[A-Za-z0-9_-]+"
            r"/toolboxes/[A-Za-z0-9_-]+/versions/[1-9][0-9]*/mcp\?api-version=v1",
            self.toolbox_endpoint,
        ):
            raise ValueError("Approval requires an explicit versioned Foundry Toolbox HTTPS endpoint.")
        if self.content_parameter in self.fixed_arguments:
            raise ValueError("The content parameter must not replace a fixed target argument.")
        if self.wiki_etag_parameter is not None:
            if (
                self.tool_name != "ado___wiki_upsert_page" or self.content_parameter != "content"
                or "etag" in self.fixed_arguments or self.fixed_arguments.get("branch") != "wikiMaster"
                or not all(isinstance(self.fixed_arguments.get(k), str) for k in ("project", "wikiIdentifier", "path"))
            ):
                raise ValueError("Conditional wiki updates require fixed wikiMaster target fields and a dynamic etag.")
        if self.review_draft_prefix is not None and self.wiki_etag_parameter is None:
            raise ValueError("Reviewed wiki drafts require a conditional target-page policy.")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) for key in self.fixed_arguments):
            raise ValueError("Fixed arguments must be tool parameters, not runtime metadata.")
        bindings = (self.proposal_page_parameter, self.proposal_section_parameter)
        if any(bindings):
            if not all(bindings) or len(set(bindings)) != 2:
                raise ValueError("Result proposals require distinct page and section parameter bindings.")
            for key in bindings:
                value = self.fixed_arguments.get(key) if key is not None else None
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Page and section bindings must reference nonblank fixed string arguments.")
        canonical_hash(self.model_dump(mode="json"))
        return self

    def arguments(self, content: str, expected_wiki_etag: str | None = None) -> dict[str, JsonValue]:
        if self.wiki_etag_parameter is not None:
            etag = TypeAdapter(WikiETag).validate_python(expected_wiki_etag)
            return {**self.fixed_arguments, self.content_parameter: content, "etag": etag}
        if expected_wiki_etag is not None:
            raise ValueError("This policy does not allow a dynamic wiki version.")
        return {**self.fixed_arguments, self.content_parameter: content}

    @classmethod
    def from_environment(cls) -> Self:
        path = os.environ.get("DOCUMENTATION_APPROVAL_POLICY")
        if not path:
            raise ValueError("Approval mode requires DOCUMENTATION_APPROVAL_POLICY pointing to a reviewed JSON file.")
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


class ProposeCall(ContractModel):
    action: Literal["propose"]
    run_id: UUID
    content: Text
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=10)]
    expected_wiki_etag: WikiETag | None = None
    review_draft: WikiSnapshot | None = None
    review_notes: WikiSnapshot | None = None


class ProposeResult(ContractModel):
    action: Literal["propose_result"]
    result: AgentResult
    proposal_index: Annotated[int, Field(strict=True, ge=0)]


class ProposalOrigin(ContractModel):
    request_id: UUID
    result_sha256: str
    proposal_index: int
    target_page: str
    target_section: str
    provenance: Provenance


class ModifyCall(ContractModel):
    action: Literal["modify"]
    pending_id: UUID
    feedback: Annotated[NonBlank, Field(max_length=1000)]
    content: Text
    review_draft: WikiSnapshot | None = None
    review_notes: WikiSnapshot | None = None


class InspectCall(ContractModel):
    action: Literal["inspect"]
    pending_id: UUID


Command = Annotated[ProposeCall | ProposeResult | ModifyCall | InspectCall, Field(discriminator="action")]
COMMAND: TypeAdapter[ProposeCall | ProposeResult | ModifyCall | InspectCall] = TypeAdapter(Command)
ARGUMENTS: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


class PendingCall(ContractModel):
    interface_version: Literal["1.0.0"] = "1.0.0"
    runtime_version: Literal["0.5.0", "0.6.0"] = "0.6.0"
    pending_id: UUID = Field(default_factory=uuid4)
    call_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    tool: str
    arguments: dict[str, JsonValue]
    args_hash: str
    policy_hash: str
    tool_hash: str
    evidence: list[Evidence]
    origin: ProposalOrigin | None = None
    review_draft: WikiSnapshot | None = None
    review_notes: WikiSnapshot | None = None
    owner: str
    session_id: str
    created_at: datetime
    expires_at: datetime
    status: Literal["pending", "modified", "rejected", "executing", "succeeded", "outcome_unknown"] = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    feedback: str | None = None
    replacement_id: UUID | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None

    def approval(self) -> Content:
        return Content.from_function_approval_request(
            id=str(self.pending_id),
            function_call=Content.from_function_call(
                str(self.call_id),
                self.tool,
                arguments=self.arguments,
                additional_properties={"server_label": "documentation_approval"},
            ),
        )

    def output(self) -> list[Content]:
        evidence = "\n".join(
            f"- {item.source}: {item.uri} (version {item.version})\n  {item.excerpt}" for item in self.evidence
        )
        return [
            Content.from_text(
                f"Pending ID: {self.pending_id}\nRun ID: {self.run_id}\nTool: {self.tool}\n"
                f"Arguments SHA-256: {self.args_hash}\n"
                f"Exact arguments: {json.dumps(self.arguments, sort_keys=True)}\n"
                f"Proposal origin: {self.origin.model_dump_json() if self.origin else 'explicit content'}\n"
                f"Expires: {self.expires_at.isoformat()}\n"
                f"Evidence (supplied by caller; not independently verified here):\n{evidence}\n"
                "Approve attempts this exact external call once. Reject executes nothing. "
                "Modify voids this call and requires a new approval. "
                "An interrupted call has an unknown outcome and is never automatically retried."
            ),
            self.approval(),
        ]


def validate_schema(schema: dict[str, Any], arguments: dict[str, JsonValue]) -> None:
    def reject_remote_refs(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (not isinstance(item, str) or not item.startswith("#")):
                    raise ValueError("External schema references are not supported for approval tools.")
                reject_remote_refs(item)
        elif isinstance(value, list):
            for item in value:
                reject_remote_refs(item)

    reject_remote_refs(schema)
    Draft202012Validator.check_schema(schema)
    if schema.get("type") != "object" or not set(arguments).issubset(schema.get("properties", {})):
        raise ValueError("Every approved argument must be declared in the discovered tool schema.")
    if not Draft202012Validator(schema).is_valid(arguments):
        raise ValueError("Proposed arguments do not match the discovered tool schema.")


class ToolConnection(Protocol):
    @property
    def spec(self) -> Tool: ...

    async def invoke_once(self, arguments: dict[str, JsonValue]) -> dict[str, Any]: ...


class FoundryToolConnection:
    def __init__(self, session: ClientSession, spec: Tool) -> None:
        self.session = session
        self.spec = spec

    async def invoke_once(self, arguments: dict[str, JsonValue]) -> dict[str, Any]:
        # FoundryToolbox.call_tool retries on connection loss. A write must not.
        # Keep the official authenticated Toolbox transport, but use its public
        # MCP session for one exact, unfiltered tools/call (including server metadata).
        result = await self.session.call_tool(self.spec.name, arguments=arguments, meta=self.spec.meta)
        if result.isError:
            raise RuntimeError("Approval-gated tool returned an error; external outcome requires reconciliation.")
        return result.model_dump(mode="json", exclude_none=True)


@asynccontextmanager
async def connect_tool(policy: ToolApprovalPolicy) -> AsyncIterator[ToolConnection]:
    if os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT") and policy.auth_mode != "managed_identity":
        raise ValueError("Hosted approval requires managed identity, not operator CLI credentials.")
    credential = AzureCliCredential() if policy.auth_mode == "azure_cli" else ManagedIdentityCredential()
    async with (
        credential,
        FoundryToolbox(
            credential,
            url=policy.toolbox_endpoint,
            allowed_tools=[policy.tool_name],
            tool_name_prefix="",
            approval_mode="always_require",
            load_tools=False,
            load_prompts=False,
        ) as toolbox,
    ):
        session = toolbox.session
        if session is None:
            raise RuntimeError("Toolbox did not establish an MCP session.")
        matches: list[Tool] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
            matches.extend(tool for tool in page.tools if tool.name == policy.tool_name)
            if not page.nextCursor:
                break
            if page.nextCursor in seen or len(seen) >= 100:
                raise ValueError("Tool discovery pagination did not terminate.")
            seen.add(page.nextCursor)
            cursor = page.nextCursor
        if len(matches) != 1:
            raise ValueError("The configured approval tool must appear exactly once in Toolbox discovery.")
        spec = matches[0]
        if spec.execution is not None and spec.execution.taskSupport != "forbidden":
            raise ValueError("Task-based tools are not supported by this single-attempt approval runtime.")
        yield FoundryToolConnection(session, spec)


Connector = Callable[[ToolApprovalPolicy], AbstractAsyncContextManager[ToolConnection]]
WikiRead = Callable[[str], Awaitable[WikiSnapshot]]


def wiki_reader_from_environment(policy: ToolApprovalPolicy) -> WikiRead | None:
    if policy.wiki_etag_parameter is None:
        return None
    from .settings import AssessmentSettings
    from .wiki_page import ToolboxWikiReader

    endpoint = os.environ.get("DOCUMENTATION_PUSH_READ_TOOLBOX")
    if not endpoint:
        raise ValueError("Conditional wiki approval requires DOCUMENTATION_PUSH_READ_TOOLBOX.")
    settings = AssessmentSettings.from_environment({**os.environ, "TOOLBOX_ENDPOINT": endpoint})
    if (
        settings.ado_project != policy.fixed_arguments["project"]
        or settings.ado_wiki != policy.fixed_arguments["wikiIdentifier"]
        or settings.auth_mode != policy.auth_mode
    ):
        raise ValueError("Wiki reader and writer must use the same configured project/wiki and authentication mode.")
    return ToolboxWikiReader(settings)


class ToolApprovalAgent(ApprovalAgentBase):
    def __init__(
        self, policy: ToolApprovalPolicy, *, connector: Connector = connect_tool, allow_local: bool = False,
        wiki_reader: WikiRead | None = None,
    ) -> None:
        super().__init__(name="documentation-tool-approval", description="Exact-call approval; no automatic writes.")
        self.policy = policy.model_copy(deep=True)
        self.connector = connector
        self.allow_local = allow_local
        self.wiki_reader = wiki_reader
        if policy.wiki_etag_parameter is not None and wiki_reader is None:
            raise ValueError("Conditional wiki updates require a target readback adapter.")

    def policy_hash(self) -> str:
        return canonical_hash(self.policy.model_dump(mode="json"))

    def check_record(self, record: PendingCall) -> None:
        if record.policy_hash != self.policy_hash() or record.tool != self.policy.tool_name:
            raise ValueError("Approval target policy changed; create a new proposal.")
        content = record.arguments.get(self.policy.content_parameter)
        etag = record.arguments.get("etag") if self.policy.wiki_etag_parameter is not None else None
        if etag is not None and not isinstance(etag, str):
            raise ValueError("Stored wiki ETag must be a string.")
        if not isinstance(content, str) or self.policy.arguments(content, etag) != record.arguments:
            raise ValueError("Stored arguments do not match the fixed target policy.")
        if record.args_hash != canonical_hash({"tool": record.tool, "arguments": record.arguments}):
            raise ValueError("Stored approval arguments hash does not match.")
        self.check_draft(record.review_draft, content, record.review_notes)

    def check_draft(self, draft: WikiSnapshot | None, content: str, notes: WikiSnapshot | None = None) -> None:
        prefix = self.policy.review_draft_prefix
        if prefix is not None:
            if draft is None or not draft.path.startswith(prefix + "/PR-") or draft.content != content:
                raise ValueError("Approval requires the exact versioned review draft in the configured draft area.")
        elif draft is not None:
            raise ValueError("This policy does not accept external draft references.")
        if notes is not None and (draft is None or notes.path != draft.path + "-review"):
            raise ValueError("Review notes must belong to the same draft revision.")

    def from_result(self, command: ProposeResult) -> tuple[ProposeCall, ProposalOrigin]:
        page_key = self.policy.proposal_page_parameter
        section_key = self.policy.proposal_section_parameter
        if page_key is None or section_key is None:
            raise ValueError("Result proposals require an explicitly configured section-aware tool.")
        result = command.result
        if result.provenance.agent_name != "documentation-agent":
            raise ValueError("Result proposals must originate from documentation-agent.")
        if command.proposal_index >= len(result.proposed_changes):
            raise ValueError("Selected proposed change does not exist.")
        change = result.proposed_changes[command.proposal_index]
        if (
            change.target_page != self.policy.fixed_arguments[page_key]
            or change.target_section != self.policy.fixed_arguments[section_key]
        ):
            raise ValueError("Proposed page or section does not match the operator's fixed target.")
        refs = set(change.evidence_refs)
        proposal = ProposeCall(
            action="propose",
            run_id=result.request_id,
            content=change.proposed_content,
            evidence=[item for item in result.evidence if item.id in refs],
        )
        origin = ProposalOrigin(
            request_id=result.request_id,
            result_sha256=canonical_hash(result.model_dump(mode="json")),
            proposal_index=command.proposal_index,
            target_page=change.target_page,
            target_section=change.target_section,
            provenance=result.provenance,
        )
        return proposal, origin

    async def proposal(
        self, command: ProposeCall, actor: str, session_id: str, origin: ProposalOrigin | None = None
    ) -> PendingCall:
        arguments = self.policy.arguments(command.content, command.expected_wiki_etag)
        self.check_draft(command.review_draft, command.content, command.review_notes)
        async with asyncio.timeout(self.policy.timeout_seconds), self.connector(self.policy) as connection:
            if connection.spec.name != self.policy.tool_name:
                raise ValueError("Tool discovery returned a different tool.")
            validate_schema(connection.spec.inputSchema, arguments)
            tool_hash = canonical_hash(connection.spec.model_dump(mode="json"))
        now = datetime.now(UTC)
        return PendingCall(
            run_id=command.run_id,
            tool=self.policy.tool_name,
            arguments=arguments,
            args_hash=canonical_hash({"tool": self.policy.tool_name, "arguments": arguments}),
            policy_hash=self.policy_hash(),
            tool_hash=tool_hash,
            evidence=command.evidence,
            origin=origin,
            review_draft=command.review_draft,
            review_notes=command.review_notes,
            owner=actor,
            session_id=session_id,
            created_at=now,
            expires_at=now + timedelta(seconds=self.policy.approval_ttl_seconds),
        )

    async def execute(self, messages: AgentRunInputs | None, session: AgentSession | None) -> list[Content]:
        if session is None:
            raise ValueError("Tool approval requires a hosting session.")
        actor = self.actor()
        decision = approval_decision(messages)
        store = await FoundryStateStore.get_or_create(STORE_NAME, user_isolation=True)
        async with store:
            if decision is not None:
                return await self.decide(store, decision, actor, session.session_id)
            try:
                command = COMMAND.validate_json(request_text(messages))
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid approval command: {exc.errors(include_input=False, include_url=False)}"
                ) from None
            if isinstance(command, (ProposeCall, ProposeResult)):
                origin = None
                if isinstance(command, ProposeResult):
                    command, origin = self.from_result(command)
                record = await self.proposal(command, actor, session.session_id, origin)
                await store.create_item(str(record.pending_id), record.model_dump(mode="json"))
                return record.output()
            item = await store.get_item(str(command.pending_id))
            if item is None:
                raise ValueError("Unknown pending approval.")
            record = PendingCall.model_validate(item.value)
            self.check_owner(record.model_dump(), actor, session.session_id)
            if isinstance(command, InspectCall):
                return [Content.from_text(record.model_dump_json())]
            self.check_pending(record.model_dump())
            self.check_record(record)
            self.check_draft(command.review_draft, command.content, command.review_notes)
            # Void before discovery/storage of a replacement; failure cannot restore
            # permission to execute the original proposal.
            record.status = "modified"
            record.feedback = command.feedback
            record.decided_by = actor
            record.decided_at = datetime.now(UTC)
            changed = await self.replace(store, str(record.pending_id), record.model_dump(mode="json"), item.etag)
            replacement = await self.proposal(
                ProposeCall(
                    action="propose", run_id=record.run_id, content=command.content, evidence=record.evidence,
                    expected_wiki_etag=(
                        TypeAdapter(WikiETag).validate_python(record.arguments.get("etag"))
                        if self.policy.wiki_etag_parameter is not None else None
                    ),
                    review_draft=command.review_draft,
                    review_notes=command.review_notes,
                ),
                actor,
                session.session_id,
                record.origin,
            )
            record.replacement_id = replacement.pending_id
            await self.replace(store, str(record.pending_id), record.model_dump(mode="json"), changed.etag)
            await store.create_item(str(replacement.pending_id), replacement.model_dump(mode="json"))
            return replacement.output()

    async def decide(
        self, store: FoundryStateStore, decision: Content, actor: str, session_id: str
    ) -> list[Content]:
        if not isinstance(decision.id, str) or type(decision.approved) is not bool:
            raise ValueError("Malformed native approval response.")
        item = await store.get_item(str(UUID(decision.id)))
        if item is None:
            raise ValueError("Unknown approval request.")
        record = PendingCall.model_validate(item.value)
        self.check_owner(record.model_dump(), actor, session_id)
        self.check_pending(record.model_dump())
        self.check_record(record)
        call = decision.function_call
        if call is None or call.name != record.tool or call.call_id != str(record.call_id):
            raise ValueError("Approval does not match the pending tool call.")
        supplied = (
            ARGUMENTS.validate_json(call.arguments)
            if isinstance(call.arguments, str)
            else ARGUMENTS.validate_python(call.arguments)
        )
        if canonical_hash({"tool": call.name, "arguments": supplied}) != record.args_hash:
            raise ValueError("Approval arguments were changed; decision rejected.")
        record.decided_by = actor
        record.decided_at = datetime.now(UTC)
        if not decision.approved:
            record.status = "rejected"
            await self.replace(store, str(record.pending_id), record.model_dump(mode="json"), item.etag)
            return [Content.from_text(record.model_dump_json())]
        if record.expires_at <= datetime.now(UTC):
            raise ValueError("Approval expired; create a new proposal.")
        async with asyncio.timeout(self.policy.timeout_seconds), self.connector(self.policy) as connection:
            if canonical_hash(connection.spec.model_dump(mode="json")) != record.tool_hash:
                raise ValueError("Tool schema or metadata changed; create a new proposal.")
            validate_schema(connection.spec.inputSchema, record.arguments)
            if record.review_draft is not None:
                if self.wiki_reader is None:
                    raise ValueError("Draft readback is not configured.")
                current_draft = await self.wiki_reader(record.review_draft.path)
                if current_draft != record.review_draft:
                    raise ValueError("Review draft changed. Generate a fresh reviewed proposal before approving.")
                if record.review_notes is not None:
                    current_notes = await self.wiki_reader(record.review_notes.path)
                    if current_notes != record.review_notes:
                        raise ValueError("Review notes changed. Generate a fresh reviewed proposal before approving.")
            if self.policy.wiki_etag_parameter is not None:
                await self.verify_wiki(record, after_write=False)
            if record.expires_at <= datetime.now(UTC):
                raise ValueError("Approval expired during tool discovery; create a new proposal.")
            record.status = "executing"
            claimed = await self.replace(store, str(record.pending_id), record.model_dump(mode="json"), item.etag)
            try:
                record.result = await connection.invoke_once(record.arguments)
                if self.policy.wiki_etag_parameter is not None:
                    verified = await self.verify_wiki(record, after_write=True)
                    record.result["wiki_readback"] = {
                        "path": verified.path, "etag": verified.etag, "uri": verified.uri,
                    }
                record.status = "succeeded"
                record.completed_at = datetime.now(UTC)
                await self.replace(store, str(record.pending_id), record.model_dump(mode="json"), claimed.etag)
            except (Exception, asyncio.CancelledError):
                # An external side effect and a state write cannot be atomic.
                # Preserve the non-retryable claim even if recording uncertainty fails.
                LOGGER.error("Approval %s has an uncertain outcome; never retry automatically.", record.pending_id)
                record.status = "outcome_unknown"
                record.result = None
                record.completed_at = datetime.now(UTC)
                await self.replace(store, str(record.pending_id), record.model_dump(mode="json"), claimed.etag)
                raise
        return [Content.from_text(record.model_dump_json())]

    async def verify_wiki(self, record: PendingCall, *, after_write: bool) -> WikiSnapshot:
        path = self.policy.fixed_arguments.get("path")
        if self.wiki_reader is None or not isinstance(path, str):
            raise ValueError("Wiki readback is not configured.")
        snapshot = await self.wiki_reader(path)
        if snapshot.path != path:
            raise ValueError("Wiki readback returned another page.")
        if after_write:
            if snapshot.content != record.arguments[self.policy.content_parameter]:
                raise ValueError("Wiki readback differs from the approved content; do not retry automatically.")
        elif snapshot.etag.strip('"') != str(record.arguments["etag"]).strip('"'):
            raise ValueError("Wiki changed since this draft was created. Reject it and generate a fresh draft.")
        return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    schemas = parser.add_mutually_exclusive_group()
    schemas.add_argument("--print-command-schema", action="store_true")
    schemas.add_argument("--print-state-schema", action="store_true")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--allow-local-tool-execution", action="store_true")
    args = parser.parse_args()
    if args.print_command_schema or args.print_state_schema:
        schema = COMMAND.json_schema() if args.print_command_schema else PendingCall.model_json_schema()
        print(json.dumps(schema, indent=2))
        return
    if args.policy is None or args.state_dir is None:
        parser.error("--policy and --state-dir are required to run the local approval server.")
    if os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT") or not args.allow_local_tool_execution:
        parser.error("This loopback-only entry point requires explicit --allow-local-tool-execution.")
    policy = ToolApprovalPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
    os.environ["AGENTSERVER_STATE_ROOT"] = str(args.state_dir.resolve())
    logging.basicConfig(level=logging.INFO)
    agent = ToolApprovalAgent(policy, allow_local=True, wiki_reader=wiki_reader_from_environment(policy))
    ResponsesHostServer(agent, history_source="agent").run(
        host="127.0.0.1", port=args.port
    )


if __name__ == "__main__":
    main()
