import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from agent_framework import Content, FunctionInvocationContext, FunctionTool
from documentation_agent.assessment import AssessmentAgent
from documentation_agent.settings import AssessmentSettings
from documentation_agent.visualization import MAX_HANDOFF_BYTES, handoff
from documentation_agent.visualization_agent_client import FoundryVisualizationClient
from documentation_agent.visualization_settings import VisualizationSettings
from documentation_agent.wiki_page import compose_page, review_notes
from pydantic import ValidationError
from test_hosted_assessment import FakeRunner, analysis_payload
from test_hosted_assessment import request_v1 as request_v1
from test_hosted_assessment import settings as settings
from test_push_flow import (
    CALLER,
    activity,
    button,
    page_flow,
    platform,
    push,
    register_and_send,
)
from test_push_flow import harness as harness

from contracts.drafts import DraftPublished
from contracts.repositories import azure_file_uri, azure_repository
from contracts.v1 import AgentResult
from contracts.visualization import ArchitectureDiagram, VisualizationOutput
from contracts.wiki import WikiSnapshot

ENDPOINT = "https://visual.services.ai.azure.com/api/projects/architecture/agents/visualizer/endpoint/protocols/a2a"
OLD_DIAGRAM = '```mermaid\ngraph LR;\n    n1["Order Sync"];\n```\n\n'
WIKI = "# Order Sync\n\n## Architecture diagram\n\n" + OLD_DIAGRAM + "## Ownership\n\nKeep this exactly.\n"


def wiki_snapshot(content, path="/Overview"):
    raw = content.encode()
    etag = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return WikiSnapshot(path=path, content=content, etag=etag, uri="https://dev.azure.com/example/wiki")


@pytest.fixture
def enabled(settings):
    return settings.model_copy(update={"visualization": VisualizationSettings(
        endpoint=ENDPOINT, agent_name="visualizer", card_version="1.0",
        guidelines_version="1.0.0", target_page="/Overview",
    )})


class SourcesRunner(FakeRunner):
    def __init__(self, *, wiki=WIKI, output=None):
        super().__init__(output)
        self.wiki = wiki

    async def analyze(self, request, instructions, guard, check=None):
        answer = json.loads(await super().analyze(request, instructions, guard, check))
        # A captured tool response, not an extra model-authored source.
        guard.calls[-1]["output"] = json.dumps({
            "page": {"url": "https://dev.azure.com/example/wiki", "content": self.wiki},
            "eTag": [wiki_snapshot(self.wiki).etag],
        })
        answer["evidence"][1]["excerpt"] = "Order Sync"
        answer["evidence"][1]["version"] = wiki_snapshot(self.wiki).etag
        return json.dumps(answer)


def visual_output(request, decision="update"):
    source = next(item for item in request.sources if item.source == "git")
    return VisualizationOutput.model_validate({
        "request_id": request.request_id, "input_sha256": request.input_sha256,
        "guidelines_version": "1.0.0", "decision": decision,
        "reason": "The architecture matches the supplied integration snapshot.",
        "diagram": {
            "direction": "LR",
            "nodes": [{"id": "n1", "label": "Order synchronization", "kind": "component", "evidence_refs": ["G1"]}],
            "edges": [],
        } if decision in {"create", "update"} else None,
        "evidence": [{
            "id": "G1", "source": "git", "uri": source.uri,
            "version": source.version, "excerpt": source.content,
        }],
        "missing_information": (
            ["The destination system is not established."] if decision == "insufficient_context" else []
        ),
    })


class Specialist:
    def __init__(self, decision="update", mutate=None):
        self.decision = decision
        self.mutate = mutate
        self.requests = []

    async def review(self, request):
        self.requests.append(request)
        output = visual_output(request, self.decision)
        if self.mutate is not None:
            data = output.model_dump(mode="json")
            self.mutate(data)
            output = VisualizationOutput.model_validate(data)
        return output


def assess(enabled, request_v1, specialist, runner=None):
    return asyncio.run(AssessmentAgent(
        enabled, runner or SourcesRunner(), visualization_client=specialist,
    ).assess(request_v1))


def test_enabled_assessment_always_delegates_once_and_preserves_prose(enabled, request_v1):
    specialist = Specialist()
    result = assess(enabled, request_v1, specialist)
    assert len(specialist.requests) == 1
    package = specialist.requests[0]
    assert package.correlation_id == request_v1.correlation_id
    assert package.subject.commit_sha == request_v1.subject.commit_sha
    assert package.current_section == "\n" + OLD_DIAGRAM
    assert {source.source for source in package.sources} == {"git", "wiki"}
    assert "DS-14" not in "".join(source.content for source in package.sources)
    assert result.proposed_changes[0].target_section == "Retries"
    diagram = result.proposed_changes[-1]
    assert diagram.target_section == "Architecture diagram"
    assert diagram.evidence_refs == ["visualization-G1"]
    assert diagram.proposed_content.startswith("```mermaid\ngraph LR;")
    assert result.requires_human_review
    assert result.visualization.input_sha256 == package.input_sha256
    assert AgentResult.model_validate_json(result.model_dump_json()) == result


def test_keep_leaves_diagram_bytes_untouched_and_records_review(enabled, request_v1):
    result = assess(enabled, request_v1, Specialist("keep"))
    base = wiki_snapshot(WIKI)
    composed = compose_page(base, result)
    assert "## Architecture diagram\n\n" + OLD_DIAGRAM + "## Ownership\n\nKeep this exactly.\n" in composed
    assert "Decision: keep" in review_notes(base, composed, result)
    assert len(result.proposed_changes) == 1


def test_create_adds_diagram_to_existing_wiki_without_altering_other_sections(enabled, request_v1):
    wiki = "# Order Sync\n\n## Ownership\n\nKeep this exactly.\n"
    result = assess(enabled, request_v1, Specialist("create"), SourcesRunner(wiki=wiki))
    base = wiki_snapshot(wiki)
    composed = compose_page(base, result)
    assert composed.startswith(wiki)
    assert "## Architecture diagram\n\n```mermaid\n" in composed
    assert "Decision: create" in review_notes(base, composed, result)


def test_insufficient_context_keeps_existing_diagram_and_surfaces_unknown(enabled, request_v1):
    result = assess(enabled, request_v1, Specialist("insufficient_context"))
    assert result.documentation_status == "insufficient_information"
    assert result.missing_information[-1].description == "The destination system is not established."
    assert len(result.proposed_changes) == 1


def test_disabled_never_invokes_specialist_or_changes_serialized_result(settings, request_v1):
    result = asyncio.run(AssessmentAgent(settings, SourcesRunner()).assess(request_v1))
    assert "visualization" not in result.model_dump()
    with pytest.raises(ValueError, match="explicit"):
        AssessmentAgent(settings, SourcesRunner(), visualization_client=Specialist())


@pytest.mark.parametrize("decision,wiki", [("create", WIKI), ("update", "# Order Sync\n"), ("keep", "# Order Sync\n")])
def test_invalid_decision_for_existing_diagram_is_rejected(enabled, request_v1, decision, wiki):
    with pytest.raises(ValueError, match="Cannot"):
        assess(enabled, request_v1, Specialist(decision), SourcesRunner(wiki=wiki))


@pytest.mark.parametrize("mutation", [
    lambda output: output.update(input_sha256="b" * 64),
    lambda output: output.update(guidelines_version="wrong"),
    lambda output: output["evidence"][0].update(version="c" * 40),
    lambda output: output["evidence"][0].update(excerpt="invented queue"),
])
def test_stale_or_ungrounded_responses_fail(enabled, request_v1, mutation):
    with pytest.raises(ValueError, match="Visualization"):
        assess(enabled, request_v1, Specialist(mutate=mutation))


def test_prose_cannot_overwrite_diagram_or_hide_it_in_grouped_proposals(enabled, request_v1):
    output = analysis_payload()
    output["proposed_changes"][0]["proposed_content"] = (
        "## Retries\nFive attempts.\n\n## Architecture diagram\nReplace everything"
    )
    specialist = Specialist()
    with pytest.raises(ValueError, match="exclusively"):
        assess(enabled, request_v1, specialist, SourcesRunner(output=output))
    assert not specialist.requests


def test_missing_wiki_read_and_oversized_context_fail_before_delegation(enabled, request_v1, monkeypatch):
    runner = SourcesRunner()
    result = asyncio.run(AssessmentAgent(enabled.model_copy(update={"visualization": None}), runner).assess(request_v1))
    calls = runner.guards[0].calls
    with pytest.raises(ValueError, match="wiki read"):
        handoff(request_v1, result, calls[:-1], enabled.visualization)
    monkeypatch.setattr("documentation_agent.visualization.MAX_HANDOFF_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        handoff(request_v1, result, calls, enabled.visualization)
    assert MAX_HANDOFF_BYTES > 10


def test_timeout_is_not_reported_as_keep(enabled, request_v1):
    class Slow:
        async def review(self, request):
            raise TimeoutError("remote agent timed out")

    with pytest.raises(TimeoutError):
        assess(enabled, request_v1, Slow())


def test_identical_diagram_cannot_be_proposed_as_an_update(enabled, request_v1):
    def unchanged(data):
        data["diagram"]["nodes"][0]["label"] = "Order Sync"

    with pytest.raises(ValueError, match="unchanged diagram"):
        assess(enabled, request_v1, Specialist(mutate=unchanged))


def test_up_to_date_assessment_stays_up_to_date_when_diagram_is_kept(enabled, request_v1):
    output = analysis_payload()
    output.update(documentation_status="up_to_date", findings=[], proposed_changes=[], requires_human_review=False)
    result = assess(enabled, request_v1, Specialist("keep"), SourcesRunner(output=output))
    assert result.documentation_status == "up_to_date"
    assert result.proposed_changes == []


def test_a2a_payload_size_limit_is_enforced(enabled, request_v1):
    payload = package(enabled, request_v1)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b" " * 128001)),
        ) as http:
            await FoundryVisualizationClient(enabled.visualization, "azure_cli").exchange(http, payload)

    with pytest.raises(ValueError, match="size limit"):
        asyncio.run(run())


@pytest.mark.parametrize("label", ['X"] --> bad', "<script>", "hello\nworld", "%%{init: x}", "a" * 81])
def test_diagram_rejects_mermaid_injection(label):
    with pytest.raises(ValidationError):
        ArchitectureDiagram.model_validate({
            "direction": "LR", "nodes": [{"id": "n1", "label": label, "kind": "component", "evidence_refs": ["G1"]}],
            "edges": [],
        })


def test_rendered_graph_uses_ado_compatible_shapes_and_evidenced_connections():
    graph = ArchitectureDiagram.model_validate({
        "direction": "LR",
        "nodes": [
            {"id": "n1", "label": "ERP", "kind": "external", "evidence_refs": ["G1"]},
            {"id": "n2", "label": "Orders", "kind": "store", "evidence_refs": ["G1"]},
        ],
        "edges": [{"source": "n1", "target": "n2", "label": "Orders (sync)", "evidence_refs": ["G1"]}],
    })
    assert graph.mermaid() == 'graph LR;\n    n1(["ERP"]);\n    n2[("Orders")];\n    n1 -->|"Orders (sync)"| n2;'
    invalid = graph.model_dump()
    invalid["edges"][0]["target"] = "n3"
    with pytest.raises(ValidationError, match="declared nodes"):
        ArchitectureDiagram.model_validate(invalid)


def test_settings_fail_closed_when_enabled_but_unconfigured(settings):
    env = {
        "DOCUMENTATION_PROJECT_ENDPOINT": settings.project_endpoint, "TOOLBOX_ENDPOINT": settings.toolbox_endpoint,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": settings.model, "DOCUMENTATION_MODEL_VERSION": settings.model_version,
        "DOCUMENTATION_ADO_PROJECT": settings.ado_project, "DOCUMENTATION_ADO_WIKI": settings.ado_wiki,
        "DOCUMENTATION_ENABLE_VISUALIZATION": "true",
    }
    with pytest.raises(ValidationError):
        AssessmentSettings.from_environment(env)
    env["DOCUMENTATION_ENABLE_VISUALIZATION"] = "false"
    assert AssessmentSettings.from_environment(env).visualization is None


def card():
    return {
        "name": "visualizer", "version": "1.0",
        "supportedInterfaces": [{"protocolBinding": "JSONRPC", "protocolVersion": "1.0", "url": ENDPOINT}],
        "skills": [{"id": "architecture-visualization"}],
    }


def package(enabled, request_v1):
    runner = SourcesRunner()
    result = asyncio.run(AssessmentAgent(enabled.model_copy(update={"visualization": None}), runner).assess(request_v1))
    return handoff(request_v1, result, runner.guards[0].calls, enabled.visualization)


@pytest.mark.parametrize("shape", ["message", "task", "data", "hostname-case"])
def test_real_a2a_v1_wire_contract_with_mock_http(enabled, request_v1, shape):
    payload = package(enabled, request_v1)
    calls = []

    def respond(request):
        calls.append(request)
        assert request.headers["A2A-Version"] == "1.0"
        if request.method == "GET":
            assert str(request.url) == ENDPOINT + "/agentCard/v1.0"
            value = card()
            if shape == "hostname-case":
                value["supportedInterfaces"][0]["url"] = ENDPOINT.replace("visual.services", "VISUAL.services")
            return httpx.Response(200, json=value)
        body = json.loads(request.content)
        assert body["method"] == "SendMessage"
        assert body["params"]["message"]["role"] == "ROLE_USER"
        assert body["params"]["configuration"]["returnImmediately"] is False
        sent = json.loads(body["params"]["message"]["parts"][0]["text"])
        assert sent["input_sha256"] == payload.input_sha256
        output = visual_output(payload)
        part = {"data": output.model_dump(mode="json")} if shape == "data" else {"text": output.model_dump_json()}
        result = {"message": {"role": "ROLE_AGENT", "parts": [part]}}
        if shape == "task":
            result = {"task": {"id": "task1", "status": {"state": "TASK_STATE_COMPLETED"},
                               "artifacts": [{"artifactId": "a1", "parts": [part]}]}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), headers={"A2A-Version": "1.0"},
        ) as http:
            return await FoundryVisualizationClient(enabled.visualization, "azure_cli").exchange(http, payload)

    assert asyncio.run(run()).decision == "update"
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["redirect", "wrong-endpoint", "wrong-version", "failed", "working", "rpc", "id"])
def test_a2a_rejects_discovery_changes_and_noncompleted_outputs(enabled, request_v1, failure):
    payload = package(enabled, request_v1)
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "GET":
            if failure == "redirect":
                return httpx.Response(302, headers={"Location": "https://untrusted.example"})
            value = card()
            if failure == "wrong-endpoint":
                value["supportedInterfaces"][0]["url"] = "https://untrusted.example"
            if failure == "wrong-version":
                value["version"] = "2"
            return httpx.Response(200, json=value)
        body = json.loads(request.content)
        response = {"jsonrpc": "2.0", "id": body["id"], "result": {
            "task": {"status": {"state": "TASK_STATE_" + failure.upper()}}
        }}
        if failure == "rpc":
            response = {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32001, "message": "secret"}}
        if failure == "id":
            response["id"] = "unrelated"
        return httpx.Response(200, json=response)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await FoundryVisualizationClient(enabled.visualization, "azure_cli").exchange(http, payload)

    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        asyncio.run(run())
    assert len(calls) == (1 if failure in {"redirect", "wrong-endpoint", "wrong-version"} else 2)


def test_prompt_definition_is_local_no_tools_and_uses_output_schema():
    path = Path(__file__).parents[2] / "src" / "agents" / "visualization-agent" / "configure.py"
    spec = importlib.util.spec_from_file_location("visualization_configure", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definition = module.definition("reviewed-model")
    assert definition["tools"] == []
    assert "version 1.0.0" in definition["instructions"]
    assert definition["text"]["format"]["schema"] == VisualizationOutput.model_json_schema()


def test_pipeline_a2a_draft_reaches_existing_human_approval(harness, monkeypatch, enabled):
    async def run():
        flow, teams, assessor, _, connection, _ = harness
        current = page_flow(harness)
        original_assess = assessor.assess.side_effect

        class PipelineRunner:
            async def analyze(self, request, instructions, guard, check=None):
                repo = azure_repository(request.subject.repo)
                uri = azure_file_uri(repo, "/src/order_sync.py", request.subject.commit_sha)
                source = "maxAttempts=3"
                reads = [
                    ("knowledge___knowledge_base_retrieve", {}, {"documents": [{"content": "DS-14"}]}),
                    ("ado___repo_file", {
                        "action": "get_content", "project": repo.project, "repositoryId": repo.repository,
                        "path": "/src/order_sync.py", "version": request.subject.commit_sha, "versionType": "Commit",
                    }, {"documents": [{"uri": uri, "content": source}]}),
                    ("ado___wiki", {
                        "action": "get_page", "project": repo.project, "wikiIdentifier": "wiki",
                        "path": current[0].path,
                    }, {"page": {"url": current[0].uri, "content": current[0].content}, "eTag": [current[0].etag]}),
                ]
                for name, arguments, value in reads:
                    context = FunctionInvocationContext(FunctionTool(name=name), arguments=arguments)

                    async def dispatch(context=context, value=value):
                        context.result = [Content.from_text(json.dumps(value))]

                    await guard.process(context, dispatch)
                result = original_assess(request)
                result.evidence[0].uri = uri
                return result.model_dump_json(exclude={"request_id", "contract_version", "provenance"})

        settings = enabled.model_copy(update={
            "ado_project": "project", "ado_organization": "test", "ado_wiki": "wiki",
            "visualization": enabled.visualization.model_copy(update={"target_page": current[0].path}),
        })
        specialist = Specialist("create")
        flow.assessor = AssessmentAgent(settings, PipelineRunner(), visualization_client=specialist)
        before = current[0]
        prepared = await register_and_send(harness, monkeypatch, push().model_copy(update={"pull_request_id": 12}))
        assert len(specialist.requests) == 1
        assert "```mermaid\ngraph LR;" in prepared["content"]
        assert "Decision: create" in prepared["review_notes"]
        assert prepared["content"].startswith(before.content)
        connection.invoke_once.assert_not_called()
        assert current[0] == before
        flow.read_draft.return_value = prepared["content"]
        flow.read_notes.return_value = prepared["review_notes"]
        with platform(CALLER):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
        connection.invoke_once.assert_not_called()
        with platform():
            review = await flow.open_review(activity(), UUID(prepared["event_id"]))
            await teams.handle(activity(value=button(review, "Approve")))
        connection.invoke_once.assert_awaited_once()
        assert current[0].content == prepared["content"]
        assert connection.invoke_once.call_args.args[0]["etag"] == before.etag

    asyncio.run(run())
