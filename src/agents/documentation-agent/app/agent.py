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
from agent_framework.exceptions import AgentInvalidRequestException
from pydantic import ValidationError

from contracts import CONTRACT_VERSION, AgentRequest, AgentResult, Provenance


def request_text(messages: AgentRunInputs | None) -> str:
    if isinstance(messages, str):
        return messages
    items = [messages] if isinstance(messages, (Message, Content)) else list(messages or [])
    if len(items) != 1:
        raise AgentInvalidRequestException("Supply exactly one AgentRequest JSON message per invocation.")
    item = items[0]
    if isinstance(item, str):
        return item
    if isinstance(item, Message):
        if item.role != "user":
            raise AgentInvalidRequestException("AgentRequest must be supplied in a user message.")
        contents = item.contents
    else:
        contents = [item]
    if len(contents) != 1 or contents[0].type != "text":
        raise AgentInvalidRequestException(
            "Supply AgentRequest as one text content item; attachments are not supported."
        )
    text = contents[0].text
    if text is None:
        raise AgentInvalidRequestException("AgentRequest text is missing.")
    return text


class DocumentationAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="documentation-agent",
            description="Validates contract v0 and returns deterministic stub provenance; no analysis or model call.",
        )

    def result(self, messages: AgentRunInputs | None) -> AgentResult:
        try:
            request = AgentRequest.model_validate_json(request_text(messages))
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
            raise AgentInvalidRequestException(f"Invalid AgentRequest: {errors}") from None
        return AgentResult(
            contract_version=CONTRACT_VERSION,
            request_id=request.request_id,
            provenance=Provenance(
                contract_version=CONTRACT_VERSION,
                agent_name="documentation-agent",
                agent_version="0.1.0",
                model="not-invoked",
                model_version="not-applicable",
                prompt_version="not-applicable",
                policy_version="0.1.0",
            ),
        )

    @overload
    def run(
        self,
        messages: AgentRunInputs | None = None,
        *,
        stream: Literal[False] = False,
        session: AgentSession | None = None,
        function_invocation_kwargs: Mapping[str, Any] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> Awaitable[AgentResponse[AgentResult]]: ...

    @overload
    def run(
        self,
        messages: AgentRunInputs | None = None,
        *,
        stream: Literal[True],
        session: AgentSession | None = None,
        function_invocation_kwargs: Mapping[str, Any] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> ResponseStream[AgentResponseUpdate, AgentResponse[AgentResult]]: ...

    def run(
        self,
        messages: AgentRunInputs | None = None,
        *,
        stream: bool = False,
        session: AgentSession | None = None,
        function_invocation_kwargs: Mapping[str, Any] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> Awaitable[AgentResponse[AgentResult]] | ResponseStream[AgentResponseUpdate, AgentResponse[AgentResult]]:
        response_id = str(uuid4())

        async def complete() -> AgentResponse[AgentResult]:
            result = self.result(messages)
            return AgentResponse(
                messages=[Message("assistant", [result.model_dump_json()])],
                response_id=response_id,
                value=result,
            )

        async def updates() -> AsyncIterator[AgentResponseUpdate]:
            response = await complete()
            yield AgentResponseUpdate(
                contents=[Content.from_text(response.text)],
                role="assistant",
                response_id=response_id,
                message_id=response_id,
            )

        async def finalize(updates: Sequence[AgentResponseUpdate]) -> AgentResponse[AgentResult]:
            text = "".join(update.text for update in updates)
            return AgentResponse(
                messages=[Message("assistant", [text])],
                response_id=response_id,
                value=AgentResult.model_validate_json(text),
            )

        if stream:
            return ResponseStream(updates(), finalizer=finalize)
        return complete()
