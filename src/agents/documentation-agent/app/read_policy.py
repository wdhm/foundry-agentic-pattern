import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from agent_framework import Content, FunctionInvocationContext, FunctionMiddleware, MiddlewareFailure
from mcp.types import CallToolResult, TextResourceContents
from pydantic import BaseModel

from contracts.evaluation import ExecutionRecord
from contracts.repositories import azure_repository, matches_azure_file
from contracts.v1 import AgentRequest

from .settings import AssessmentSettings

READ_TOOLS = (
    "knowledge___knowledge_base_retrieve",
    "github___get_file_contents",
    "ado___wiki",
    "ado___wit_work_item",
)


def read_tools(settings: AssessmentSettings) -> tuple[str, ...]:
    return READ_TOOLS + (("ado___repo_file",) if settings.ado_organization is not None else ())


def require_read(name: str, arguments: Mapping[str, Any], request: AgentRequest, settings: AssessmentSettings) -> None:
    if name not in read_tools(settings):
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
        if name == "ado___repo_file":
            try:
                azure_repo = azure_repository(request.subject.repo)
            except ValueError as exc:
                raise MiddlewareFailure(str(exc)) from exc
            if azure_repo.organization != settings.ado_organization or azure_repo.project != settings.ado_project:
                raise MiddlewareFailure("Azure Repos reads must use the configured organization and project.")
            if arguments.get("repositoryId") != azure_repo.repository:
                raise MiddlewareFailure("Azure Repos reads must target the requested repository.")
            if arguments.get("action") != "get_content":
                raise MiddlewareFailure("Only Azure Repos file get_content is allowed.")
            if arguments.get("versionType") != "Commit" or arguments.get("version") != request.subject.commit_sha:
                raise MiddlewareFailure(
                    "Azure Repos reads must use the exact requested commit, with versionType=Commit."
                )
            path = arguments.get("path")
            if (
                not isinstance(path, str) or not path.startswith("/") or "\\" in path or "%" in path
                or any(part in {"", ".", ".."} for part in path[1:].split("/"))
            ):
                raise MiddlewareFailure("Azure Repos reads require an explicit absolute repository file path.")
        elif name == "ado___wiki":
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
    # GitHub get_file_contents returns a status line plus the file as an embedded text resource.
    documents = [
        {"uri": str(item.resource.uri), "content": item.resource.text}
        for item in result.content
        if item.type == "resource" and isinstance(item.resource, TextResourceContents)
    ]
    if documents:
        return json.dumps({"documents": documents})
    text = [item.text for item in result.content if item.type == "text"]
    if not text:
        raise MiddlewareFailure("Source tool returned no readable content.")
    return "\n".join(text)


def require_read_output(name: str, arguments: Mapping[str, Any], output: str, request: AgentRequest) -> None:
    if name != "ado___repo_file":
        return
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise MiddlewareFailure("Azure Repos returned invalid file resource JSON.") from exc
    documents = payload.get("documents") if isinstance(payload, dict) else None
    repo = azure_repository(request.subject.repo)
    if not isinstance(documents, list) or not documents or any(
        not isinstance(doc, dict) or not isinstance(doc.get("content"), str)
        or not isinstance(doc.get("uri"), str)
        or not matches_azure_file(doc["uri"], repo, arguments["path"], request.subject.commit_sha)
        for doc in documents
    ):
        raise MiddlewareFailure("Azure Repos returned no matching commit-pinned file resource.")


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
        require_read_output(context.function.name, arguments, output, self.request)
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
