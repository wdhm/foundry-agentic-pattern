"""Shared native approval transport and state preconditions."""

import hashlib
import json
import os
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from typing import Any, Literal, overload
from uuid import uuid4

from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    AgentRunInputs,
    AgentSession,
    BaseAgent,
    Content,
    Message,
    ResponseStream,
)
from azure.ai.agentserver.core import get_request_context
from azure.ai.agentserver.core.storage import (
    FoundryStateStore,
    FoundryStorageConflictError,
    FoundryStoragePreconditionError,
    StateStoreItemRef,
)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def approval_decision(messages: AgentRunInputs | None) -> Content | None:
    items = [messages] if isinstance(messages, Message) else messages
    if isinstance(items, Sequence) and not isinstance(items, str) and len(items) == 1:
        item = items[0]
        if isinstance(item, Message) and len(item.contents) == 1:
            candidate = item.contents[0]
            if candidate.type == "function_approval_response":
                if item.role != "user":
                    raise ValueError("Approval responses must be user input.")
                return candidate
    return None


class ApprovalAgentBase(BaseAgent):
    allow_local: bool = False

    def actor(self) -> str:
        context = get_request_context()
        hosted = bool(os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT"))
        if hosted and context.user_id:
            return context.user_id
        if self.allow_local and not hosted:
            return "local-unverified"
        raise ValueError(
            "Verified platform user context is required; no reviewer identity is accepted in request text."
        )

    @staticmethod
    def check_owner(record: dict[str, Any], actor: str, session_id: str) -> None:
        if record["owner"] != actor or record["session_id"] != session_id:
            raise ValueError("Approval belongs to a different reviewer or session.")

    @staticmethod
    def check_pending(record: dict[str, Any]) -> None:
        if record["status"] != "pending":
            raise ValueError("Proposal is no longer pending; duplicate or stale decision rejected.")

    @staticmethod
    async def replace(store: FoundryStateStore, key: str, record: dict[str, Any], etag: str) -> StateStoreItemRef:
        try:
            return await store.set_item(key, record, if_match=etag)
        except (FoundryStorageConflictError, FoundryStoragePreconditionError):
            raise ValueError("Another decision already changed this proposal; replay rejected.") from None

    async def execute(self, messages: AgentRunInputs | None, session: AgentSession | None) -> list[Content]:
        raise NotImplementedError

    @overload
    def run(
        self,
        messages: AgentRunInputs | None = None,
        *,
        stream: Literal[False] = False,
        session: AgentSession | None = None,
        function_invocation_kwargs: Mapping[str, Any] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> Awaitable[AgentResponse[Any]]: ...

    @overload
    def run(
        self,
        messages: AgentRunInputs | None = None,
        *,
        stream: Literal[True],
        session: AgentSession | None = None,
        function_invocation_kwargs: Mapping[str, Any] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> ResponseStream[AgentResponseUpdate, AgentResponse[Any]]: ...

    def run(
        self,
        messages: AgentRunInputs | None = None,
        *,
        stream: bool = False,
        session: AgentSession | None = None,
        function_invocation_kwargs: Mapping[str, Any] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> Awaitable[AgentResponse[Any]] | ResponseStream[AgentResponseUpdate, AgentResponse[Any]]:
        response_id = str(uuid4())

        async def complete() -> AgentResponse[Any]:
            contents = await self.execute(messages, session)
            return AgentResponse(messages=[Message("assistant", contents)], response_id=response_id)

        async def updates() -> AsyncIterator[AgentResponseUpdate]:
            response = await complete()
            yield AgentResponseUpdate(
                contents=response.messages[0].contents,
                role="assistant",
                response_id=response_id,
                message_id=response_id,
            )

        def finalize(updates: Sequence[AgentResponseUpdate]) -> AgentResponse[Any]:
            return AgentResponse(
                messages=[Message("assistant", [content for update in updates for content in update.contents])],
                response_id=response_id,
            )

        return ResponseStream(updates(), finalizer=finalize) if stream else complete()
