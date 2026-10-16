import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_framework import (
    Agent,
    BaseChatClient,
    ChatResponse,
    Content,
    FunctionInvocationContext,
    FunctionInvocationLayer,
    FunctionTool,
    Message,
    MiddlewareFailure,
)
from agent_framework.exceptions import AgentInvalidRequestException
from agent_framework_foundry_hosting import ResponsesHostServer
from documentation_agent.assessment import AssessmentAgent, FoundryAnalysisRunner
from documentation_agent.main import create_server
from documentation_agent.read_policy import READ_TOOLS, ReadOnlyPolicy, parse_read_result, require_read
from documentation_agent.settings import AssessmentSettings
from httpx import ASGITransport, AsyncClient
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents
from pydantic import ValidationError

from contracts.v1 import AgentRequest, AgentResult


@pytest.fixture
def settings():
    return AssessmentSettings(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        toolbox_endpoint="https://example.services.ai.azure.com/api/projects/demo/toolboxes/reads/mcp?api-version=v1",
        model="example-model",
        model_version="example-version",
        ado_project="demo-project",
        ado_wiki="demo-project.wiki",
        auth_mode="azure_cli",
    )


@pytest.fixture
def request_v1():
    return AgentRequest.model_validate(
        {
            "contract_version": "1.0.0",
            "request_id": str(uuid4()),
            "correlation_id": str(uuid4()),
            "trigger": "cli",
            "requested_by": "demo-reviewer",
            "subject": {"repo": "example/repo", "commit_sha": "a" * 40, "changed_paths": ["config.json"]},
            "context": {"wiki_page_paths": ["/Overview"], "work_item_ids": [1]},
            "documentation_standard_ref": "DS-14",
        }
    )


def analysis_payload():
    return {
        "documentation_status": "gaps_found",
        "findings": [
            {
                "category": "configuration",
                "severity": "medium",
                "description": "DS-14: Retry configuration is undocumented.",
                "evidence_refs": ["G1", "W1"],
            }
        ],
        "proposed_changes": [
            {
                "target_page": "/Overview",
                "target_section": "Retries",
                "proposed_content": "Retry up to five times.",
                "evidence_refs": ["G1"],
            }
        ],
        "missing_information": [],
        "evidence": [
            {
                "id": "G1",
                "source": "git",
                "uri": "https://github.com/example/repo/blob/" + "a" * 40 + "/config.json",
                "version": "a" * 40,
                "excerpt": '"maxAttempts": 5',
            },
            {
                "id": "W1",
                "source": "wiki",
                "uri": "https://dev.azure.com/example/wiki",
                "version": '"etag1"',
                "excerpt": "Order Sync overview",
            },
        ],
        "confidence": 0.8,
        "requires_human_review": True,
    }


class FakeRunner:
    def __init__(self, output=None, *, read_sources=True):
        self.output = analysis_payload() if output is None else output
        self.read_sources = read_sources
        self.guards = []

    async def analyze(self, request, instructions, guard):
        self.guards.append(guard)
        assert "Gap-analysis instructions" in instructions
        if self.read_sources:
            reads = [
                ("knowledge___knowledge_base_retrieve", {}, {"documents": [{"content": "DS-14"}]}),
                (
                    "github___get_file_contents",
                    {"owner": "example", "repo": "repo", "sha": request.subject.commit_sha, "path": "config.json"},
                    {"documents": [{"content": '{"maxAttempts": 5}'}]},
                ),
                (
                    "ado___wiki",
                    {
                        "project": "demo-project",
                        "wikiIdentifier": "demo-project.wiki",
                        "action": "get_page",
                        "path": "/Overview",
                    },
                    {
                        "page": {"url": "https://dev.azure.com/example/wiki", "content": "Order Sync overview"},
                        "eTag": ['"etag1"'],
                    },
                ),
            ]
            for name, arguments, output in reads:
                context = FunctionInvocationContext(FunctionTool(name=name), arguments=arguments)

                async def dispatch(context=context, output=output):
                    context.result = [Content.from_text(json.dumps(output))]

                await guard.process(context, dispatch)
        return json.dumps(self.output)


def test_valid_assessment_returns_v1_with_runtime_provenance(settings, request_v1):
    runner = FakeRunner()
    agent = AssessmentAgent(settings, runner)
    response = asyncio.run(agent.run(request_v1.model_dump_json()))
    result = AgentResult.model_validate_json(response.text)
    assert result.request_id == request_v1.request_id
    assert result.provenance.model == settings.model
    assert result.provenance.agent_name == "documentation-agent"
    assert result.provenance.agent_version == "0.3.0"
    assert result.provenance.prompt_version.startswith("sha256:")
    assert result == response.value
    assert len(runner.guards[0].calls) == 3


def test_no_cross_request_tool_state(settings, request_v1):
    runner = FakeRunner()
    agent = AssessmentAgent(settings, runner)

    async def run():
        await asyncio.gather(agent.run(request_v1.model_dump_json()), agent.run(request_v1.model_dump_json()))

    asyncio.run(run())
    assert runner.guards[0] is not runner.guards[1]
    assert len(runner.guards[0].calls) == len(runner.guards[1].calls) == 3


def test_invalid_request_never_calls_model(settings):
    runner = FakeRunner()
    with pytest.raises(AgentInvalidRequestException):
        asyncio.run(AssessmentAgent(settings, runner).run('{"requested_by":"private-input"}'))
    assert not runner.guards


@pytest.mark.parametrize("mutation", ["ref", "version", "excerpt", "metadata", "review"])
def test_bad_model_output_is_not_returned(settings, request_v1, mutation):
    output = analysis_payload()
    if mutation == "ref":
        output["findings"][0]["evidence_refs"] = ["does-not-exist"]
    elif mutation == "version":
        output["evidence"][0]["version"] = "b" * 40
    elif mutation == "excerpt":
        output["evidence"][0]["excerpt"] = "private-model-output"
    elif mutation == "metadata":
        output["request_id"] = str(uuid4())
    else:
        output["requires_human_review"] = False
    with pytest.raises(ValueError) as exc:
        asyncio.run(AssessmentAgent(settings, FakeRunner(output)).run(request_v1.model_dump_json()))
    assert "private-model-output" not in str(exc.value)


def test_unread_sources_are_rejected(settings, request_v1):
    with pytest.raises(ValueError, match="actual source read"):
        asyncio.run(AssessmentAgent(settings, FakeRunner(read_sources=False)).run(request_v1.model_dump_json()))


def test_stream_contains_only_validated_result(settings, request_v1):
    async def run():
        stream = AssessmentAgent(settings, FakeRunner()).run(request_v1.model_dump_json(), stream=True)
        updates = [update async for update in stream]
        final = await stream.get_final_response()
        assert len(updates) == 1
        assert AgentResult.model_validate_json(updates[0].text) == final.value
        failed = AssessmentAgent(settings, FakeRunner({})).run(request_v1.model_dump_json(), stream=True)
        with pytest.raises(ValueError):
            await anext(failed.__aiter__())

    asyncio.run(run())


@pytest.mark.parametrize(
    "tool,args",
    [
        ("ado___wiki_upsert_page", {}),
        ("call_tool", {"name": "ado___wiki_upsert_page"}),
        ("tool_search", {}),
        ("unknown___get_file_contents", {}),
        ("ado___wiki", {"project": "demo-project", "action": "delete_page"}),
        ("ado___wit_work_item", {"project": "demo-project", "action": "update", "id": 1}),
        ("ado___wit_work_item", {"project": "other-project", "action": "get", "id": 1}),
        ("ado___wit_work_item", {"project": "demo-project", "action": "get", "id": 999}),
        ("ado___wit_work_item", {"project": "demo-project", "action": "get", "id": True}),
        (
            "ado___wiki",
            {
                "project": "demo-project",
                "action": "get_page",
                "wikiIdentifier": "demo-project.wiki",
                "path": "/unrequested",
            },
        ),
        ("github___get_file_contents", {"owner": "other", "repo": "repo", "sha": "a" * 40, "path": "config.json"}),
        ("github___get_file_contents", {"owner": "example", "repo": "repo", "sha": "main", "path": "config.json"}),
        (
            "github___get_file_contents",
            {"owner": "example", "repo": "repo", "sha": "a" * 40, "ref": "main", "path": "config.json"},
        ),
        ("github___get_file_contents", {"owner": "example", "repo": "repo", "sha": "a" * 40, "path": "../secret"}),
    ],
)
def test_read_guard_blocks_before_tool_executes(settings, request_v1, tool, args):
    guard = ReadOnlyPolicy(request_v1, settings)
    context = FunctionInvocationContext(FunctionTool(name=tool), arguments=args)
    called = False

    async def dispatch():
        nonlocal called
        called = True

    with pytest.raises(MiddlewareFailure):
        asyncio.run(guard.process(context, dispatch))
    assert not called
    assert guard.calls == []


def test_allowed_work_item_read(settings, request_v1):
    require_read("ado___wit_work_item", {"action": "get", "project": "demo-project", "id": 1}, request_v1, settings)


def test_mcp_errors_fail_closed():
    with pytest.raises(MiddlewareFailure, match="error"):
        parse_read_result(CallToolResult(isError=True, content=[TextContent(type="text", text="private-error")]))
    assert parse_read_result(CallToolResult(content=[], structuredContent={"documents": []})) == '{"documents": []}'
    with pytest.raises(MiddlewareFailure):
        parse_read_result(CallToolResult(content=[]))


def test_embedded_file_resource_becomes_document():
    uri = "repo://owner/repo/sha/abc/contents/config/settings.json"
    result = CallToolResult(
        content=[
            TextContent(type="text", text="successfully downloaded text file (SHA: 5fc5)"),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(uri=uri, mimeType="text/plain", text='{"maxAttempts": 5}'),
            ),
        ]
    )
    assert json.loads(parse_read_result(result)) == {"documents": [{"uri": uri, "content": '{"maxAttempts": 5}'}]}


def test_unknown_mode_and_missing_settings_fail(monkeypatch):
    monkeypatch.setenv("DOCUMENTATION_MODE", "typo")
    with pytest.raises(ValueError, match="DOCUMENTATION_MODE"):
        create_server()
    with pytest.raises(ValidationError):
        AssessmentSettings.from_environment({})


def test_production_auth_default_is_not_a_fallback_chain(settings):
    payload = settings.model_dump(exclude={"auth_mode"})
    assert AssessmentSettings.model_validate(payload).auth_mode == "managed_identity"


def test_example_request_uses_v1_contract():
    path = Path(__file__).parents[2] / "src/agents/documentation-agent/examples/assessment-request.json"
    request = AgentRequest.model_validate_json(path.read_text())
    assert request.context.wiki_page_paths
    assert request.context.work_item_ids


@pytest.mark.parametrize("endpoint", ["http://example.com/project", "https://user:password@example.com/project"])
def test_untrusted_endpoint_configuration_is_rejected(settings, endpoint):
    values = settings.model_dump()
    values["toolbox_endpoint"] = endpoint
    with pytest.raises(ValidationError):
        AssessmentSettings.model_validate(values)


def test_startup_selects_assessment_explicitly_without_contacting_azure(settings, monkeypatch):
    monkeypatch.setenv("DOCUMENTATION_MODE", "assessment")
    env = {
        "DOCUMENTATION_PROJECT_ENDPOINT": settings.project_endpoint,
        "TOOLBOX_ENDPOINT": settings.toolbox_endpoint,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": settings.model,
        "DOCUMENTATION_MODEL_VERSION": settings.model_version,
        "DOCUMENTATION_ADO_PROJECT": settings.ado_project,
        "DOCUMENTATION_ADO_WIKI": settings.ado_wiki,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    captured = []

    def host(agent, **kwargs):
        captured.append(agent)
        return object()

    monkeypatch.setattr("documentation_agent.main.ResponsesHostServer", host)
    create_server()
    assert isinstance(captured[0], AssessmentAgent)
    assert captured[0].provenance.model == settings.model
    monkeypatch.delenv("TOOLBOX_ENDPOINT")
    with pytest.raises(ValidationError):
        create_server()


def test_tool_and_model_failures_propagate(settings, request_v1):
    class BrokenRunner:
        async def analyze(self, request, instructions, guard):
            raise ConnectionError("source unavailable")

    with pytest.raises(ConnectionError):
        asyncio.run(AssessmentAgent(settings, BrokenRunner()).run(request_v1.model_dump_json()))


def test_timeout_cancels_work(settings, request_v1):
    settings.timeout_seconds = 1
    cancelled = False

    class SlowRunner:
        async def analyze(self, request, instructions, guard):
            nonlocal cancelled
            try:
                await asyncio.sleep(10)
            finally:
                cancelled = True

    with pytest.raises(TimeoutError):
        asyncio.run(AssessmentAgent(settings, SlowRunner()).run(request_v1.model_dump_json()))
    assert cancelled


def test_actual_sdk_tool_loop_obeys_guard(settings, request_v1):
    calls = []

    class ReplayClient(FunctionInvocationLayer, BaseChatClient):
        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            return ChatResponse(
                messages=[
                    Message(
                        "assistant",
                        [
                            Content.from_function_call(
                                "write-1",
                                "ado___wiki",
                                arguments={"action": "delete_page", "project": "demo-project"},
                            )
                        ],
                    )
                ]
            )

    def wiki(action: str, project: str) -> str:
        calls.append(action)
        return "unexpected"

    async def run():
        agent = Agent(
            client=ReplayClient(),
            tools=[FunctionTool(name="ado___wiki", func=wiki)],
            middleware=[ReadOnlyPolicy(request_v1, settings)],
        )
        await agent.run("Write something")

    with pytest.raises(MiddlewareFailure):
        asyncio.run(run())
    assert calls == []


def test_http_host_uses_assessment_contract(settings, request_v1):
    async def run():
        server = ResponsesHostServer(AssessmentAgent(settings, FakeRunner()), history_source="agent")
        async with AsyncClient(transport=ASGITransport(app=server), base_url="http://localhost") as client:
            response = await client.post(
                "/responses",
                json={
                    "input": request_v1.model_dump_json(),
                    "stream": False,
                    "store": False,
                },
            )
            response.raise_for_status()
            body = response.json()
            assert body["status"] == "completed"
            result = AgentResult.model_validate_json(body["output"][0]["content"][0]["text"])
            assert result.request_id == request_v1.request_id
            invalid = await client.post("/responses", json={"input": "{}", "stream": False, "store": False})
            assert invalid.json()["status"] == "failed"
            assert invalid.json()["output"] == []

    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "missing-tool", "model-error", "approval", "filtered"])
def test_production_runner_wiring_and_cleanup(settings, request_v1, monkeypatch, fault):
    """Run the production adapter against in-memory SDK boundaries; no Azure resources."""
    events = []

    class Resource:
        async def __aenter__(self):
            events.append(("enter", type(self).__name__))
            return self

        async def __aexit__(self, *args):
            events.append(("exit", type(self).__name__))

    class Credential(Resource):
        pass

    class Project(Resource):
        def __init__(self, *, endpoint, credential):
            assert endpoint == settings.project_endpoint

    class Toolbox(Resource):
        def __init__(self, credential, **kwargs):
            assert kwargs["url"] == settings.toolbox_endpoint
            assert kwargs["allowed_tools"] == READ_TOOLS
            assert kwargs["parse_tool_results"] is parse_read_result
            assert kwargs["tool_name_prefix"] == ""
            self.functions = [FunctionTool(name=name) for name in READ_TOOLS]
            if fault == "missing-tool":
                self.functions.pop()

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["model"] == settings.model
            assert kwargs["function_invocation_configuration"]["allow_concurrent_invocation"] is False
            self.client = Resource()

    class ModelAgent:
        def __init__(self, **kwargs):
            assert kwargs["default_options"]["store"] is False
            assert kwargs["default_options"]["response_format"].__name__ == "AnalysisOutput"
            assert isinstance(kwargs["middleware"][0], ReadOnlyPolicy)
            assert {tool.name for tool in kwargs["tools"]} == set(READ_TOOLS)

        async def run(self, text):
            assert json.loads(text)["request_id"] == str(request_v1.request_id)
            if fault == "model-error":
                raise RuntimeError("Model unavailable")
            return SimpleNamespace(
                user_input_requests=["approval"] if fault == "approval" else [],
                finish_reason="content_filter" if fault == "filtered" else "stop",
                text='{"example":"analysis"}',
            )

    monkeypatch.setattr("azure.identity.aio.AzureCliCredential", Credential)
    monkeypatch.setattr("azure.ai.projects.aio.AIProjectClient", Project)
    monkeypatch.setattr("agent_framework_foundry_hosting.FoundryToolbox", Toolbox)
    monkeypatch.setattr("agent_framework.foundry.FoundryChatClient", Client)
    monkeypatch.setattr("agent_framework.Agent", ModelAgent)
    invocation = FoundryAnalysisRunner(settings).analyze(
        request_v1,
        "instructions",
        ReadOnlyPolicy(request_v1, settings),
    )
    if fault:
        with pytest.raises(RuntimeError):
            asyncio.run(invocation)
    else:
        assert asyncio.run(invocation) == '{"example":"analysis"}'
    expected = ["Toolbox", "Project", "Credential"]
    if fault != "missing-tool":
        expected.insert(0, "Resource")
    assert [name for action, name in events if action == "exit"] == expected
