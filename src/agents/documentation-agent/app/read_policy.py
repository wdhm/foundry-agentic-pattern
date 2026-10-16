import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from agent_framework import Content, FunctionInvocationContext, FunctionMiddleware, MiddlewareFailure
from mcp.types import CallToolResult
from pydantic import BaseModel

from contracts.evaluation import ExecutionRecord
from contracts.v1 import AgentRequest

from .settings import AssessmentSettings

READ_TOOLS = (
    "knowledge___knowledge_base_retrieve",
    "github___get_file_contents",
    "ado___wiki",
    "ado___wit_work_item",
)


def require_read(name: str, arguments: Mapping[str, Any], request: AgentRequest, settings: AssessmentSettings) -> None:
    if name not in READ_TOOLS:
        raise MiddlewareFailure(f"Tool is not allowed for documentation assessment: {name}")
    if name == "github___get_file_contents":
        repo = request.subject.repo
        if repo.startswith("https://"):
            url = urlsplit(repo)
            if url.netloc != "github.com" or url.query or url.fragment:
                raise MiddlewareFailure("Only explicit GitHub repositories are supported.")
            repo = url.path.strip("/")
        if repo != f"{arguments.get('owner')}/{arguments.get('repo')}":
            raise MiddlewareFailure("Git reads must target the requested repository.")
        if arguments.get("sha", arguments.get("ref")) != request.subject.commit_sha:
            raise MiddlewareFailure("Git reads must use the exact requested commit SHA.")
        if "ref" in arguments and arguments["ref"] != request.subject.commit_sha:
            raise MiddlewareFailure("Conflicting Git ref is not allowed.")
        path = arguments.get("path")
        if not isinstance(path, str) or not path or any(part in {"", ".", ".."} for part in path.split("/")):
            raise MiddlewareFailure("Git reads require an explicit relative path without traversal.")
        if "\\" in path or path.startswith("/") or "%" in path:
            raise MiddlewareFailure("Git reads require an unambiguous repository-relative path.")
    elif name.startswith("ado___"):
        if arguments.get("project") != settings.ado_project:
            raise MiddlewareFailure("ADO reads must use the configured project.")
        if name == "ado___wiki":
            if arguments.get("action") != "get_page":
                raise MiddlewareFailure("Only wiki get_page is allowed; writes are blocked.")
            if arguments.get("wikiIdentifier") != settings.ado_wiki:
                raise MiddlewareFailure("Wiki reads must use the configured wiki.")
            if arguments.get("path") not in request.context.wiki_page_paths:
                raise MiddlewareFailure("Wiki page was not included in the request.")
        else:
            if arguments.get("action") != "get":
                raise MiddlewareFailure("Only work-item get is allowed; writes are blocked.")
            item_id = arguments.get("id")
            if type(item_id) is not int or item_id not in request.context.work_item_ids:
                raise MiddlewareFailure("Work item was not included in the request.")


def parse_read_result(result: CallToolResult) -> str:
    if result.isError:
        raise MiddlewareFailure("Source tool returned an error; assessment stopped.")
    if result.structuredContent is not None:
        return json.dumps(result.structuredContent)
    text = [item.text for item in result.content if item.type == "text"]
    if not text:
        raise MiddlewareFailure("Source tool returned no readable content.")
    return "\n".join(text)


class ReadOnlyPolicy(FunctionMiddleware):
    """Enforce actions before dispatch and retain evidence for this invocation only."""

    def __init__(
        self, request: AgentRequest, settings: AssessmentSettings, record: ExecutionRecord | None = None
    ) -> None:
        self.request = request
        self.settings = settings
        self.calls: list[dict[str, Any]] = []
        self.record = record

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        arguments = (
            context.arguments.model_dump() if isinstance(context.arguments, BaseModel) else dict(context.arguments)
        )
        require_read(context.function.name, arguments, self.request, self.settings)
        await call_next()
        result = context.result
        if isinstance(result, str):
            output = result
        elif isinstance(result, list) and all(isinstance(item, Content) and item.type == "text" for item in result):
            output = "\n".join(item.text or "" for item in result)
        else:
            raise MiddlewareFailure("Unexpected source-tool result shape; assessment stopped.")
        if not output.strip():
            raise MiddlewareFailure("Source tool returned empty output; assessment stopped.")
        server, tool = context.function.name.split("___", 1)
        self.calls.append(
            {
                "type": "mcp_call",
                "server_label": server,
                "name": tool,
                "status": "completed",
                "arguments": json.dumps(arguments),
                "output": output,
            }
        )
        if self.record is not None:
            self.record.tool_calls.append(dict(self.calls[-1]))
