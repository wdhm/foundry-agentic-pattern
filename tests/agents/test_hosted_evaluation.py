import asyncio
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_framework import (
    Agent,
    BaseChatClient,
    ChatContext,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    FunctionTool,
    Message,
    MiddlewareFailure,
)
from agent_framework.exceptions import AgentInvalidRequestException
from agent_framework_foundry_hosting import ResponsesHostServer
from documentation_agent.assessment import AssessmentAgent
from documentation_agent.evaluation import EvaluationAgent, FoundrySuppliedRunner, verify_snapshots
from documentation_agent.execution import CaptureModel
from documentation_agent.main import create_server
from documentation_agent.read_policy import ReadOnlyPolicy
from documentation_agent.settings import AssessmentSettings
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from contracts.evaluation import EvaluationRequest, EvaluationResponse, ExecutionRecord
from contracts.v1 import AnalysisOutput


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


@pytest.fixture
def settings():
    return AssessmentSettings(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        toolbox_endpoint="https://example.services.ai.azure.com/api/projects/demo/toolboxes/test/mcp?api-version=v1",
        model="example-model",
        model_version="test-model-version",
        ado_project="test-project",
        ado_wiki="test-wiki",
        auth_mode="azure_cli",
    )


@pytest.fixture
def payload():
    return {
        "interface_version": "1.0.0",
        "source_mode": "supplied_sources",
        "request": {
            "contract_version": "1.0.0",
            "request_id": str(uuid4()),
            "correlation_id": str(uuid4()),
            "trigger": "eval",
            "requested_by": "test-caller",
            "subject": {"repo": "example/repo", "commit_sha": "a" * 40, "changed_paths": ["settings.json"]},
            "documentation_standard_ref": "supplied DS-14",
        },
        "task": "Assess the supplied retry settings. The wiki is unavailable.",
        "standard": {"content": "DS-14: document retries.", "sha256": digest("DS-14: document retries.")},
        "sources": [
            {
                "id": "config",
                "source": "git",
                "uri": "https://github.com/example/repo/blob/" + "a" * 40 + "/settings.json",
                "version": "a" * 40,
                "availability": "available",
                "content": '{"maxAttempts": 3}',
                "sha256": digest('{"maxAttempts": 3}'),
            },
            {
                "id": "wiki",
                "source": "wiki",
                "uri": "https://dev.azure.com/example/wiki",
                "availability": "unavailable",
                "version": None,
                "content": None,
                "sha256": None,
            },
        ],
    }


def output_for(payload):
    source = payload["sources"][0]
    return {
        "documentation_status": "insufficient_information",
        "findings": [],
        "proposed_changes": [],
        "missing_information": [{"description": "Wiki content and version unavailable.", "expected_source": "wiki"}],
        "evidence": [
            {
                "id": "config-read",
                "source": "git",
                "uri": source["uri"],
                "version": source["version"],
                "excerpt": '"maxAttempts": 3',
            }
        ],
        "confidence": 0.5,
        "requires_human_review": True,
    }


class SuppliedDouble:
    def __init__(self, output):
        self.output = output
        self.received = []

    async def analyze(self, payload, record):
        self.received.append((payload, record))
        record.model_calls.append({"status": "completed", "input": payload.model_dump(mode="json")})
        return json.dumps(self.output)


def test_supplied_result_is_correlated_and_has_no_fabricated_tools(settings, payload):
    runner = SuppliedDouble(output_for(payload))
    response = asyncio.run(EvaluationAgent(settings, supplied=runner).run(json.dumps(payload)))
    report = EvaluationResponse.model_validate_json(response.text)
    assert report.execution.status == "completed"
    assert report.execution.source_mode == "supplied_sources"
    assert str(report.result.request_id) == payload["request"]["request_id"]
    assert report.execution.request_id == report.result.request_id
    assert str(report.execution.correlation_id) == payload["request"]["correlation_id"]
    assert report.result.provenance.model == settings.model
    assert report.result.provenance.prompt_version == "sha256:" + digest(report.execution.instructions)
    assert not report.execution.tool_calls and not report.execution.tool_schemas
    assert len(report.execution.model_calls) == 1
    assert report.execution.sources[1].content is None


@pytest.mark.parametrize("field", ["expected_status", "gold", "reference_answer", "baseline"])
def test_gold_and_baselines_rejected_before_model(settings, payload, field):
    payload[field] = "Do not show to model"
    runner = SuppliedDouble({})
    with pytest.raises(ValueError):
        asyncio.run(EvaluationAgent(settings, supplied=runner).run(json.dumps(payload)))
    assert not runner.received


@pytest.mark.parametrize(
    "mutation", ["hash", "standard", "unknown-field", "duplicate", "wrong-sha", "unavailable-data"]
)
def test_bad_snapshot_envelope_rejected(payload, mutation):
    if mutation == "hash":
        payload["sources"][0]["content"] = "Changed"
    elif mutation == "standard":
        payload["standard"]["sha256"] = "0" * 64
    elif mutation == "unknown-field":
        payload["sources"][0]["expected_answer"] = "secret gold"
    elif mutation == "duplicate":
        payload["sources"].append(deepcopy(payload["sources"][0]))
    elif mutation == "wrong-sha":
        payload["sources"][0]["version"] = "b" * 40
    else:
        payload["sources"][1]["content"] = "Sneaked-in wiki"
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(payload)


def test_live_cannot_receive_snapshot_override(payload):
    payload["source_mode"] = "live_sources"
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(payload)


def test_extra_source_not_in_bundle_cannot_be_cited(payload):
    output = output_for(payload)
    output["evidence"][0]["uri"] = "https://example.com/unsupplied"
    with pytest.raises(ValueError, match="available supplied source"):
        verify_snapshots(AnalysisOutput.model_validate(output), EvaluationRequest.model_validate(payload))


def test_unavailable_wiki_cannot_be_cited(payload):
    output = output_for(payload)
    output["evidence"].append(
        {
            "id": "invented-wiki",
            "source": "wiki",
            "uri": payload["sources"][1]["uri"],
            "version": "invented-etag",
            "excerpt": "Invented wiki text",
        }
    )
    with pytest.raises(ValueError):
        verify_snapshots(AnalysisOutput.model_validate(output), EvaluationRequest.model_validate(payload))


def test_excerpt_must_be_from_snapshot(payload):
    output = output_for(payload)
    output["evidence"][0]["excerpt"] = '"maxAttempts": 999'
    with pytest.raises(ValueError, match="content"):
        verify_snapshots(AnalysisOutput.model_validate(output), EvaluationRequest.model_validate(payload))


def test_production_assessment_rejects_evaluation_envelope(settings, payload):
    with pytest.raises(AgentInvalidRequestException):
        asyncio.run(AssessmentAgent(settings).evaluate(json.dumps(payload)))


def test_opt_in_is_required(monkeypatch):
    monkeypatch.setenv("DOCUMENTATION_MODE", "evaluation")
    monkeypatch.delenv("DOCUMENTATION_ENABLE_EVALUATION", raising=False)
    with pytest.raises(ValueError, match="explicit"):
        create_server()


def record_for(payload):
    request = EvaluationRequest.model_validate(payload)
    return ExecutionRecord(
        execution_id=uuid4(),
        request_id=request.request.request_id,
        correlation_id=request.request.correlation_id,
        source_mode=request.source_mode,
        instructions="test instructions",
    )


def test_real_sdk_model_middleware_captures_input_output_and_usage(payload):
    record = record_for(payload)

    class Replay(ChatMiddlewareLayer, BaseChatClient):
        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            return ChatResponse(
                messages=[Message("assistant", ["actual response"])],
                model="example",
                response_id="actual-id",
                usage_details={"input_token_count": 12, "output_token_count": 3},
            )

    async def run():
        agent = Agent(
            client=Replay(middleware=[CaptureModel(record, tools_disabled=True)]),
            instructions="test instructions",
            tools=[],
            default_options={"tool_choice": "none", "store": False},
        )
        await agent.run("actual input")

    asyncio.run(run())
    call = record.model_calls[0]
    assert call["status"] == "completed" and call["response_id"] == "actual-id"
    assert call["usage"]["input_token_count"] == 12
    assert "actual input" in json.dumps(call["input"])
    assert "actual response" in json.dumps(call["output"])
    assert "headers" not in call


def test_capture_rejects_attempted_tool_call_with_tools_disabled(payload):
    record = record_for(payload)
    context = ChatContext(
        client=SimpleNamespace(),
        messages=[],
        options={"tool_choice": "none"},
    )

    async def call_next():
        context.result = ChatResponse(
            messages=[
                Message(
                    "assistant",
                    [
                        Content.from_function_call("id", "wiki_upsert_page", arguments={}),
                    ],
                )
            ]
        )

    with pytest.raises(MiddlewareFailure):
        asyncio.run(CaptureModel(record, tools_disabled=True).process(context, call_next))


def test_no_source_network_or_toolbox_in_supplied_production_runner(settings, payload, monkeypatch):
    events = []

    class Resource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            events.append("closed")

    class Credential(Resource):
        pass

    class Project(Resource):
        def __init__(self, **kwargs):
            assert kwargs["endpoint"] == settings.project_endpoint

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["function_invocation_configuration"] == {"enabled": False}
            assert isinstance(kwargs["middleware"][0], CaptureModel)
            self.client = Resource()

    class Model:
        def __init__(self, **kwargs):
            assert kwargs["tools"] == []
            assert kwargs["default_options"]["tool_choice"] == "none"
            assert kwargs["default_options"]["store"] is False
            assert "No tools are available" in kwargs["instructions"]

        async def run(self, body):
            assert json.loads(body)["sources"] == payload["sources"]
            return SimpleNamespace(user_input_requests=[], finish_reason="stop", text=json.dumps(output_for(payload)))

    def forbidden(*args, **kwargs):
        pytest.fail("Supplied-source path must never construct a toolbox")

    monkeypatch.setattr("agent_framework_foundry_hosting.FoundryToolbox", forbidden)
    monkeypatch.setattr("azure.identity.aio.AzureCliCredential", Credential)
    monkeypatch.setattr("azure.ai.projects.aio.AIProjectClient", Project)
    monkeypatch.setattr("agent_framework.foundry.FoundryChatClient", Client)
    monkeypatch.setattr("agent_framework.Agent", Model)
    record = record_for(payload)
    from documentation_agent.evaluation import supplied_instructions

    record.instructions = supplied_instructions(settings)
    result = asyncio.run(FoundrySuppliedRunner(settings).analyze(EvaluationRequest.model_validate(payload), record))
    assert json.loads(result) == output_for(payload)
    assert len(events) == 3


def test_http_and_stream_transport_preserve_result_and_execution(settings, payload):
    async def run():
        agent = EvaluationAgent(settings, supplied=SuppliedDouble(output_for(payload)))
        server = ResponsesHostServer(agent, history_source="agent")
        async with AsyncClient(transport=ASGITransport(app=server), base_url="http://localhost") as client:
            response = await client.post(
                "/responses", json={"input": json.dumps(payload), "stream": False, "store": False}
            )
            assert response.json()["status"] == "completed"
            report = EvaluationResponse.model_validate_json(response.json()["output"][0]["content"][0]["text"])
            assert report.result.request_id == report.execution.request_id
        stream = agent.run(json.dumps(payload), stream=True)
        parts = [part async for part in stream]
        assert len(parts) == 1
        report = EvaluationResponse.model_validate_json(parts[0].text)
        assert report == (await stream.get_final_response()).value

    asyncio.run(run())


def test_snapshot_calls_do_not_leak_between_requests(settings, payload):
    runner = SuppliedDouble(output_for(payload))
    agent = EvaluationAgent(settings, supplied=runner)

    async def run():
        responses = await asyncio.gather(agent.evaluate(json.dumps(payload)), agent.evaluate(json.dumps(payload)))
        assert responses[0].execution.execution_id != responses[1].execution.execution_id
        assert len(responses[0].execution.model_calls) == len(responses[1].execution.model_calls) == 1

    asyncio.run(run())


def test_real_model_tool_loop_is_captured_without_changing_tool_outputs(settings, payload):
    record = record_for(payload)
    record.source_mode = "live_sources"
    request = EvaluationRequest.model_validate(payload).request
    guard = ReadOnlyPolicy(request, settings, record)

    class Replay(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.step = 0

        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            self.step += 1
            if self.step == 1:
                contents = [
                    Content.from_function_call(
                        "knowledge-call", "knowledge___knowledge_base_retrieve", arguments={"query": "standard"}
                    )
                ]
            else:
                contents = [Content.from_text("analysis complete")]
            return ChatResponse(messages=[Message("assistant", contents)], response_id=f"model-{self.step}")

    def retrieve(query: str) -> str:
        return '{"documents":[{"content":"DS-14: document retries."}]}'

    async def run():
        client = Replay(middleware=[CaptureModel(record)])
        function = FunctionTool(name="knowledge___knowledge_base_retrieve", func=retrieve)
        agent = Agent(client=client, tools=[function], middleware=[guard])
        response = await agent.run("Assess")
        assert response.text == "analysis complete"

    asyncio.run(run())
    assert len(record.model_calls) == 2
    assert len(record.tool_calls) == 1
    assert record.tool_calls[0]["name"] == "knowledge_base_retrieve"
    assert json.loads(record.tool_calls[0]["arguments"]) == {"query": "standard"}
    assert "DS-14" in record.tool_calls[0]["output"]
    assert "function_call" in json.dumps(record.model_calls[0]["output"])
    assert record.model_calls[1]["response_id"] == "model-2"


def test_live_evaluation_uses_the_same_assessment_without_supplied_runner(settings, payload):
    live_payload = {"interface_version": "1.0.0", "source_mode": "live_sources", "request": payload["request"]}

    class LiveDouble:
        async def analyze(self, request, instructions, guard):
            guard.calls.append(
                {
                    "type": "mcp_call",
                    "status": "completed",
                    "server_label": "knowledge",
                    "name": "knowledge_base_retrieve",
                    "arguments": "{}",
                    "output": '{"documents":[]}',
                }
            )
            guard.record.tool_calls.append(deepcopy(guard.calls[0]))
            guard.record.tool_schemas.append(
                {
                    "name": "knowledge___knowledge_base_retrieve",
                    "parameters": {"type": "object"},
                }
            )
            guard.record.model_calls.append({"status": "completed", "response_id": "test-model-response"})
            output = output_for(payload)
            output["evidence"] = []
            return json.dumps(output)

    class NeverSupplied:
        async def analyze(self, *args):
            pytest.fail("Live mode must never use supplied runner")

    async def run():
        agent = EvaluationAgent(settings, live=AssessmentAgent(settings, LiveDouble()), supplied=NeverSupplied())
        report = await agent.evaluate(json.dumps(live_payload))
        assert report.execution.source_mode == "live_sources"
        assert len(report.execution.tool_calls) == len(report.execution.tool_schemas) == 1
        assert report.execution.status == "completed"

    asyncio.run(run())


def test_supplied_model_claims_without_capture_do_not_become_completed_results(settings, payload):
    class Unobserved:
        async def analyze(self, envelope, record):
            return json.dumps(output_for(payload))

    with pytest.raises(ValueError, match="incomplete"):
        asyncio.run(EvaluationAgent(settings, supplied=Unobserved()).evaluate(json.dumps(payload)))


def test_supplied_timeout_propagates(settings, payload):
    settings.timeout_seconds = 1

    class Slow:
        async def analyze(self, envelope, record):
            await asyncio.sleep(30)

    with pytest.raises(TimeoutError):
        asyncio.run(EvaluationAgent(settings, supplied=Slow()).evaluate(json.dumps(payload)))


def test_records_omit_raw_sdk_and_provider_fields(payload):
    from documentation_agent.execution import messages_data

    msg = Message(
        "user",
        [Content.from_text("allowed text")],
        additional_properties={"Authorization": "secret"},
        raw_representation={"key": "secret"},
    )
    exported = json.dumps(messages_data([msg]))
    assert "allowed text" in exported
    assert "secret" not in exported and "Authorization" not in exported


def test_evaluation_response_schema_is_valid_and_correlated(settings, payload):
    from jsonschema import Draft202012Validator

    result = asyncio.run(
        EvaluationAgent(settings, supplied=SuppliedDouble(output_for(payload))).evaluate(json.dumps(payload))
    )
    schema = EvaluationResponse.model_json_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))
