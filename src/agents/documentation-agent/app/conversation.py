"""Read-only conversation alongside, never instead of, exact-call approval."""

import asyncio
import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self
from uuid import uuid4

from agent_framework import AgentRunInputs, AgentSession, Content, Message
from azure.ai.agentserver.core.storage import (
    FoundryStateStore,
    FoundryStorageConflictError,
    FoundryStoragePreconditionError,
)
from pydantic import Field

from contracts.models import ContractModel, NonBlank, RequestContext, Subject
from contracts.repositories import azure_repository
from contracts.v1 import AgentRequest

from .agent import request_text
from .approval import ToolApprovalAgent
from .approval_common import ApprovalAgentBase, approval_decision, canonical_hash
from .gateway import route_model_client
from .read_policy import ReadOnlyPolicy, parse_read_result, read_tools
from .settings import AssessmentSettings

LOGGER = logging.getLogger(__name__)
STORE = "documentation-conversations-v1"
MAX_TEXT = 8000
MAX_HISTORY = 12
MAX_HISTORY_CHARS = 32000
ChatText = Annotated[NonBlank, Field(max_length=MAX_TEXT)]


class ConversationSources(ContractModel):
    subject: Subject
    context: RequestContext
    documentation_standard_ref: NonBlank

    def request(self, owner: str) -> AgentRequest:
        return AgentRequest(
            contract_version="1.0.0", request_id=uuid4(), correlation_id=uuid4(),
            trigger="conversation", requested_by=owner, subject=self.subject,
            context=self.context, documentation_standard_ref=self.documentation_standard_ref,
        )


class ChatTurn(ContractModel):
    role: Literal["user", "assistant"]
    text: ChatText


class ChatHistory(ContractModel):
    owner: NonBlank
    session_id: NonBlank
    channel: NonBlank
    turns: Annotated[list[ChatTurn], Field(max_length=MAX_HISTORY)]


class ConversationRunner(Protocol):
    async def reply(
        self, turns: Sequence[ChatTurn], instructions: str, guard: ReadOnlyPolicy
    ) -> str: ...


class FoundryConversationRunner:
    def __init__(self, settings: AssessmentSettings) -> None:
        self.settings = settings

    async def reply(self, turns: Sequence[ChatTurn], instructions: str, guard: ReadOnlyPolicy) -> str:
        from agent_framework import Agent
        from agent_framework.foundry import FoundryChatClient
        from agent_framework_foundry_hosting import FoundryToolbox
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

        credential = AzureCliCredential() if self.settings.auth_mode == "azure_cli" else ManagedIdentityCredential()
        async with (
            credential,
            AIProjectClient(endpoint=self.settings.project_endpoint, credential=credential) as project,
            FoundryToolbox(
                credential, url=self.settings.toolbox_gateway_endpoint or self.settings.toolbox_endpoint,
                allowed_tools=read_tools(self.settings), tool_name_prefix="",
                approval_mode="never_require", parse_tool_results=parse_read_result,
            ) as toolbox,
        ):
            missing = set(read_tools(self.settings)) - {function.name for function in toolbox.functions}
            if missing:
                raise RuntimeError(f"Conversation toolbox is missing required read tools: {', '.join(sorted(missing))}")
            client = FoundryChatClient(
                project_client=project, model=self.settings.model,
                function_invocation_configuration={
                    "max_iterations": 12, "max_function_calls": 20,
                    "max_consecutive_errors_per_request": 1, "terminate_on_unknown_calls": True,
                    "include_detailed_errors": False, "allow_concurrent_invocation": False,
                },
            )
            route_model_client(client, self.settings)
            async with client.client:
                agent = Agent(
                    client=client, name="documentation-conversation", instructions=instructions,
                    tools=toolbox.functions, middleware=[guard], default_options={"store": False},
                )
                response = await agent.run([Message(turn.role, [turn.text]) for turn in turns])
                if response.user_input_requests:
                    raise RuntimeError("Read-only conversation cannot request or submit tool approval.")
                if response.finish_reason in {"length", "content_filter"}:
                    raise RuntimeError("Conversation response was incomplete or filtered.")
                return response.text


def structured_command(text: str) -> bool:
    # Malformed structured commands must fail validation, not fall through to a model.
    return text.lstrip().startswith(("{", "[", "```json"))


class ConversationService:
    def __init__(
        self, settings: AssessmentSettings, sources: ConversationSources,
        runner: ConversationRunner | None = None,
    ) -> None:
        self.settings = settings.model_copy(deep=True)
        self.sources = sources.model_copy(deep=True)
        repository_instructions = ""
        if sources.subject.repo.startswith("https://dev.azure.com/"):
            repo = azure_repository(sources.subject.repo)
            if repo.organization != settings.ado_organization or repo.project != settings.ado_project:
                raise ValueError("Conversation repository must match the configured ADO organization and project.")
            repository_instructions = (
                "\nFor EVERY ado___repo_file call, copy these exact arguments; add only the absolute file path:\n"
                + json.dumps({
                    "action": "get_content", "project": repo.project, "repositoryId": repo.repository,
                    "version": sources.subject.commit_sha, "versionType": "Commit",
                })
                + "\nrepositoryId is the exact repository URL segment above, not the project name or a guessed alias."
            )
        self.runner = runner if runner is not None else FoundryConversationRunner(self.settings)
        prompt = (Path(__file__).parent / "prompts" / "conversation-v1.txt").read_text(encoding="utf-8")
        self.instructions = (
            prompt + "\n\nOperator-reviewed source scope:\n" + sources.model_dump_json()
            + "\nADO project: " + settings.ado_project + "\nWiki: " + settings.ado_wiki
            + "\nAvailable read tools: " + ", ".join(read_tools(settings))
            + repository_instructions
        )
        self.scope_hash = canonical_hash({
            "sources": self.sources.model_dump(mode="json"),
            "settings": self.settings.model_dump(mode="json"), "instructions": self.instructions,
        })

    @classmethod
    def from_environment(cls) -> Self:
        path = os.environ.get("DOCUMENTATION_CHAT_SOURCES")
        toolbox = os.environ.get("DOCUMENTATION_CHAT_READ_TOOLBOX")
        if not path or not toolbox:
            raise ValueError("Chat requires DOCUMENTATION_CHAT_SOURCES and DOCUMENTATION_CHAT_READ_TOOLBOX.")
        settings = AssessmentSettings.from_environment({**os.environ, "TOOLBOX_ENDPOINT": toolbox})
        sources = ConversationSources.model_validate_json(Path(path).read_text(encoding="utf-8"))
        return cls(settings, sources)

    async def answer(self, text: str, *, owner: str, session_id: str, channel: str) -> str:
        turn = ChatTurn(role="user", text=text)
        identity = {"owner": owner, "session_id": session_id, "channel": channel}
        key = canonical_hash({**identity, "scope": self.scope_hash})
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=True)
        async with store:
            item = await store.get_item(key)
            history = (
                ChatHistory.model_validate(item.value) if item is not None
                else ChatHistory(owner=owner, session_id=session_id, channel=channel, turns=[])
            )
            if {field: getattr(history, field) for field in identity} != identity:
                raise ValueError("Conversation history belongs to another user, session or channel.")
            turns = [*history.turns, turn]
            # Keep whole user/assistant exchanges; reserve room for the next answer.
            while len(turns) >= MAX_HISTORY or sum(len(t.text) for t in turns) > MAX_HISTORY_CHARS - MAX_TEXT:
                del turns[:2]
            guard = ReadOnlyPolicy(self.sources.request(owner), self.settings)
            async with asyncio.timeout(self.settings.timeout_seconds):
                answer = await self.runner.reply(turns, self.instructions, guard)
            reply = ChatTurn(role="assistant", text=answer)
            history.turns = [*turns, reply]
            try:
                if item is None:
                    await store.create_item(key, history.model_dump(mode="json"))
                else:
                    await store.set_item(key, history.model_dump(mode="json"), if_match=item.etag)
            except (FoundryStorageConflictError, FoundryStoragePreconditionError):
                raise ValueError("Another chat turn changed this conversation; resend your question.") from None
        LOGGER.info("Read-only conversation completed using %d source calls.", len(guard.calls))
        return reply.text


class ConversationRouter(ApprovalAgentBase):
    """Retain the native approval wire format; only ordinary text enters chat."""

    def __init__(self, approval: ToolApprovalAgent, conversation: ConversationService) -> None:
        super().__init__(name="documentation-agent", description="Read-only chat and explicit documentation approval.")
        self.approval = approval
        self.conversation = conversation

    async def execute(self, messages: AgentRunInputs | None, session: AgentSession | None) -> list[Content]:
        if approval_decision(messages) is not None:
            return await self.approval.execute(messages, session)
        text = request_text(messages)
        if structured_command(text):
            return await self.approval.execute(messages, session)
        if session is None:
            raise ValueError("Conversation requires a hosting session.")
        answer = await self.conversation.answer(
            text, owner=self.approval.actor(), session_id=session.session_id, channel="responses",
        )
        return [Content.from_text(answer)]
