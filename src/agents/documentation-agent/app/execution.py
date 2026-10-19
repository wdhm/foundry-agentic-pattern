"""Request-scoped evidence, returned only by the explicitly enabled evaluation interface."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from agent_framework import ChatContext, ChatMiddleware, ChatResponse, Message, MiddlewareFailure

from contracts.evaluation import ExecutionRecord


def messages_data(messages: list[Message]) -> list[dict[str, Any]]:
    # Deliberately omit raw SDK/provider representations, headers and additional_properties.
    return [
        {
            "role": message.role,
            "content": [
                {
                    key: value
                    for key, value in {
                        "type": content.type,
                        "text": content.text,
                        "call_id": content.call_id,
                        "name": content.name,
                        "arguments": content.arguments,
                        "result": content.result,
                    }.items()
                    if value is not None
                }
                for content in message.contents
            ],
        }
        for message in messages
    ]


class CaptureModel(ChatMiddleware):
    def __init__(self, record: ExecutionRecord, *, tools_disabled: bool = False) -> None:
        self.record = record
        self.tools_disabled = tools_disabled

    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if context.stream:
            raise MiddlewareFailure("Evidence capture requires buffered model responses.")
        if self.tools_disabled and (
            (context.options or {}).get("tools") or (context.options or {}).get("tool_choice") != "none"
        ):
            raise MiddlewareFailure("Supplied-source evaluation cannot enable tools.")
        entry: dict[str, Any] = {
            "index": len(self.record.model_calls),
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "input": messages_data(list(context.messages)),
        }
        self.record.model_calls.append(entry)
        await call_next()
        response = context.result
        if not isinstance(response, ChatResponse):
            raise MiddlewareFailure("Unexpected model response; execution evidence is incomplete.")
        entry.update(
            status="completed",
            completed_at=datetime.now(UTC).isoformat(),
            response_id=response.response_id,
            model=response.model,
            finish_reason=response.finish_reason,
            output=messages_data(list(response.messages)),
            usage=response.usage_details,
        )
        # Ensure evidence is transportable now, not after returning an apparent success.
        json.dumps(entry)
        if self.tools_disabled and any(
            content.type in {"function_call", "function_approval_request"}
            for message in response.messages
            for content in message.contents
        ):
            raise MiddlewareFailure("Model attempted a tool call in tools-disabled evaluation.")
