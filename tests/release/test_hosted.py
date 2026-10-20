"""Offline hosted transport/artifact/gate tests. No Azure credential discovery."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from contracts.v1 import AgentResult
from tools.cli import main as trigger_main
from tools.cli import parser
from tools.hosted import (
    HostedArtifact,
    assessment_provenance,
    evaluator_item,
    invoke_hosted,
    result_from_response,
    validate_hosted_version,
)
from tools.hosted_release import FoundryHostedRelease, HostedReleasePlan, prepare_candidate
from tools.release import main
from tools.release_sources import load_cases

ROOT = Path(__file__).parents[2]


@pytest.fixture
def definition():
    return {
        "kind": "hosted",
        "container_configuration": {"image": "offline.azurecr.io/documentation-agent@sha256:" + "a" * 64},
        "cpu": "0.5",
        "memory": "1Gi",
        "protocol_versions": [{"protocol": "responses", "version": "2.0.0"}],
        "environment_variables": {
            "DOCUMENTATION_MODE": "assessment",
            "DOCUMENTATION_AUTH_MODE": "managed_identity",
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://offline.example/api/projects/test",
            "TOOLBOX_ENDPOINT": "https://offline.example/api/projects/test/toolboxes/reads/mcp",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "offline-model",
            "DOCUMENTATION_MODEL_VERSION": "2026-09-22",
            "DOCUMENTATION_ADO_PROJECT": "test",
            "DOCUMENTATION_ADO_WIKI": "test.wiki",
            "HOST": "0.0.0.0",
            "PORT": "8088",
        },
    }


@pytest.fixture
def artifact(definition):
    return HostedArtifact(
        image=definition["container_configuration"]["image"],
        source_commit="b" * 40,
        build_reference="offline-reviewed-build-only",
        readiness_review_reference="offline-P1-P2-review-only",
        runtime_provenance=assessment_provenance(definition),
    )


@pytest.fixture
def version(definition):
    return {"name": "documentation-agent", "version": "4", "status": "active", "definition": definition}


@pytest.fixture
def cases():
    return load_cases(ROOT / "evals/datasets/suite.json", ROOT)[1]


@pytest.fixture
def raw(cases, artifact):
    result = AgentResult(
        contract_version="1.0.0",
        request_id=cases[0]["request"].request_id,
        provenance=artifact.runtime_provenance,
        documentation_status="gaps_found",
        findings=[{"category": "mock", "severity": "low", "description": "offline", "evidence_refs": ["e1"]}],
        proposed_changes=[],
        missing_information=[],
        evidence=[{
            "id": "e1", "source": "git", "uri": cases[0]["sources"][0]["uri"],
            "version": cases[0]["request"].subject.commit_sha, "excerpt": "offline excerpt",
        }],
        confidence=0.5,
        requires_human_review=True,
    )
    return {
        "id": "offline-response", "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": result.model_dump_json()}]}],
    }


def session(status="active", version="4", session_id="offline-session"):
    return SimpleNamespace(
        agent_session_id=session_id, status=status,
        version_indicator=SimpleNamespace(type="version_ref", agent_version=version),
    )


def project_for(raw):
    project = MagicMock()
    project.agents.create_session.return_value = session()
    project.agents.get_session.return_value = session()
    client = project.get_openai_client.return_value.__enter__.return_value
    client.responses.create.return_value.model_dump.return_value = raw
    return project, client


def test_hosted_cli_is_primary():
    args = parser().parse_args([
        "invoke", "--project-endpoint", "https://offline.example/api/projects/test",
        "--agent-version", "4", "--model-version", "2026-09-22", "--repo", "example/repo",
        "--commit", "a" * 40, "--documentation-standard-ref", "DS-14", "--requested-by", "test",
    ])
    assert args.agent_kind == "hosted" and args.agent_name is None


def test_version_bound_bare_request_preserves_runtime_provenance(cases, raw, artifact):
    project, client = project_for(raw)
    report = invoke_hosted(project, cases[0]["request"], "documentation-agent", "4", artifact)
    assert report["agent_version"] == "4"
    assert report["result"]["provenance"]["agent_version"] == artifact.runtime_provenance.agent_version
    assert report["result"]["provenance"]["agent_version"] != report["agent_version"]
    assert report["agent_session_id"] == "offline-session"
    assert report["routing"] == "version_specific_session_not_serving_path_proof"
    create = project.agents.create_session.call_args.kwargs
    assert create["version_indicator"].as_dict() == {"type": "version_ref", "agent_version": "4"}
    project.get_openai_client.assert_called_once_with(agent_name="documentation-agent")
    kwargs = client.responses.create.call_args.kwargs
    assert json.loads(kwargs["input"]) == cases[0]["request"].model_dump(mode="json")
    assert kwargs["extra_body"] == {"agent_session_id": "offline-session"}
    assert "agent_reference" not in kwargs["extra_body"]
    assert "tool_choice" not in kwargs and "previous_response_id" not in kwargs
    project.agents.update_details.assert_not_called()
    project.agents.delete_session.assert_not_called()


@pytest.mark.parametrize("status", ["failed", "expired", "deleted", "deleting"])
def test_failed_session_never_invokes(status, cases, raw, artifact):
    project, client = project_for(raw)
    project.agents.create_session.return_value = session(status)
    with pytest.raises(ValueError, match="not ready"):
        invoke_hosted(project, cases[0]["request"], "documentation-agent", "4", artifact)
    client.responses.create.assert_not_called()


def test_session_polling_checks_bound_version(monkeypatch, cases, raw, artifact):
    project, client = project_for(raw)
    project.agents.create_session.return_value = session("creating")
    project.agents.get_session.return_value = session(version="5")
    monkeypatch.setattr("tools.hosted.time.sleep", lambda _: None)
    with pytest.raises(ValueError, match="not bound"):
        invoke_hosted(project, cases[0]["request"], "documentation-agent", "4", artifact)
    client.responses.create.assert_not_called()


@pytest.mark.parametrize("problem", ["stub", "auth", "model", "image", "protocol", "legacy", "policy", "inactive"])
def test_hosted_validation_fails_closed(problem, version, artifact):
    changed = deepcopy(version)
    definition = changed["definition"]
    if problem == "stub":
        definition["environment_variables"]["DOCUMENTATION_MODE"] = "stub"
    elif problem == "auth":
        definition["environment_variables"]["DOCUMENTATION_AUTH_MODE"] = "azure_cli"
    elif problem == "model":
        definition["environment_variables"]["DOCUMENTATION_MODEL_VERSION"] = "wrong"
    elif problem == "image":
        definition["container_configuration"]["image"] = "offline.azurecr.io/agent:latest"
    elif problem == "protocol":
        definition["protocol_versions"] = []
    elif problem == "legacy":
        definition["image"] = definition["container_configuration"]["image"]
    elif problem == "policy":
        artifact.runtime_provenance.policy_version = "invented"
    else:
        changed["status"] = "creating"
    with pytest.raises(ValueError):
        validate_hosted_version(changed, artifact, "https://offline.example/api/projects/test", "2026-09-22")


@pytest.mark.parametrize(
    "problem", ["request", "provenance", "v0", "analysis", "pending", "approval", "git", "refusal"]
)
def test_bad_hosted_result_is_never_wrapped_as_analysis(problem, cases, raw, artifact):
    changed = deepcopy(raw)
    content = changed["output"][0]["content"][0]
    result = json.loads(content["text"])
    if problem == "request":
        result["request_id"] = str(cases[1]["request"].request_id)
    elif problem == "provenance":
        result["provenance"]["agent_version"] = "4"
    elif problem == "v0":
        result["contract_version"] = "0.1.0"
    elif problem == "analysis":
        for key in ("request_id", "contract_version", "provenance"):
            result.pop(key)
    elif problem == "pending":
        changed["status"] = "in_progress"
    elif problem == "approval":
        changed["output"].append({"type": "mcp_approval_request"})
    elif problem == "git":
        result["evidence"][0]["version"] = "f" * 40
    else:
        content["type"] = "refusal"
    content["text"] = json.dumps(result)
    with pytest.raises(ValueError):
        result_from_response(changed, cases[0]["request"], artifact)


def test_hosted_eval_uses_actual_request_result_no_gold_or_tool_claims(cases, raw, artifact):
    result = result_from_response(raw, cases[0]["request"], artifact)
    row = evaluator_item(cases[0], {"result": result.model_dump(mode="json")}, "P1 instructions")
    assert json.loads(row["query"][1]["content"]) == cases[0]["request"].model_dump(mode="json")
    assert "reference_answer" not in row["query"][1]["content"] and "source_allowlist" not in row["query"][1]["content"]
    assert "tool_calls" not in row and "tool_definitions" not in row
    returned = json.loads(row["response"][0]["content"][0]["text"])
    assert returned["provenance"] == artifact.runtime_provenance.model_dump()
    with pytest.raises(ValueError, match="supplied-source"):
        evaluator_item(cases[2], {}, "P1 instructions")


@pytest.fixture
def plan(definition, artifact):
    return HostedReleasePlan(
        project_endpoint="https://offline.example/api/projects/test",
        agent_name="documentation-agent", base_version="3", serving_version="2",
        expected_endpoint={"version_selector": {"version_selection_rules": [
            {"type": "FixedRatio", "agent_version": "2", "traffic_percentage": 100},
        ]}, "protocol_configuration": {"responses": {}}, "authorization_schemes": ["Entra"]},
        expected_identity={"client_id": "offline"},
        candidate_definition=definition,
        model_version="2026-09-22", eval_model_version="judge-version",
        thresholds={"groundedness": 4, "task_adherence": 1, "tool_call_accuracy": 4},
        approval_reference="offline-only", writer_hold_reference="offline-only",
        evaluator_compatibility_reference="offline-only", approved_by="offline-test",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        artifact=artifact,
        serving_path_proof={
            "agent_name": "documentation-agent", "version": "2", "agent_session_id": "serving-session",
            "response_id": "serving-response", "observed_at": datetime.now(UTC) - timedelta(minutes=1),
            "selection": "fresh_named_endpoint_session_without_version_override", "evidence_reference": "offline-only",
        },
    )


@pytest.fixture
def cloud(plan):
    cloud = MagicMock(spec=FoundryHostedRelease)
    cloud.agent.return_value = {
        "name": plan.agent_name, "agent_endpoint": deepcopy(plan.expected_endpoint),
        "instance_identity": deepcopy(plan.expected_identity), "versions": {"latest": {"version": "3"}},
    }
    def version(name, selected):
        return {"name": name, "version": selected, "status": "active",
                "definition": deepcopy(plan.candidate_definition), "metadata": {"retained": "true"}}
    cloud.version.side_effect = version
    cloud.create.return_value = {"name": plan.agent_name, "version": "4"}
    cloud.await_candidate.return_value = version(plan.agent_name, "4")
    cloud.model_version.side_effect = lambda name: (
        plan.model_version if name == "offline-model" else plan.eval_model_version
    )
    return cloud


def test_candidate_primitive_uses_digest_and_real_returned_version_only(plan, cloud, tmp_path):
    assert prepare_candidate(cloud, plan, "judge", tmp_path) == "4"
    assert cloud.create.call_args.args[1] == {"retained": "true"}
    saved = json.loads((tmp_path / "candidate.json").read_text())
    assert saved["artifact"]["image"] == plan.artifact.image and saved["version"] == "4"
    assert saved["promoted"] is False
    assert not hasattr(cloud, "respond")  # Never inherits prompt transport/evaluation assumptions.


@pytest.mark.parametrize("problem", ["latest", "identity", "model", "resources", "registry", "proof", "race"])
def test_hosted_candidate_preconditions_block_before_mutation(problem, plan, cloud, tmp_path):
    if problem == "latest":
        rule = cloud.agent.return_value["agent_endpoint"]["version_selector"]["version_selection_rules"][0]
        rule["agent_version"] = "@latest"
    elif problem == "identity":
        cloud.agent.return_value["instance_identity"] = {}
    elif problem == "model":
        cloud.model_version.side_effect = lambda _: "wrong"
    elif problem == "resources":
        plan.candidate_definition["cpu"] = "4"
        original = cloud.version.side_effect
        def version(name, selected):
            result = original(name, selected)
            result["definition"]["cpu"] = "0.5"
            return result
        cloud.version.side_effect = version
    elif problem == "registry":
        plan.candidate_definition["container_configuration"]["registry_connection_id"] = "new-auth"
    elif problem == "proof":
        plan.serving_path_proof.selection = "version_specific_candidate"
    else:
        changed = deepcopy(cloud.agent.return_value)
        changed["versions"]["latest"]["version"] = "9"
        cloud.agent.side_effect = [cloud.agent.return_value, changed]
    # Explicit original registry configuration, not the plan's mutated mapping.
    if problem == "registry":
        original = cloud.version.side_effect
        def version(name, selected):
            result = original(name, selected)
            result["definition"]["container_configuration"].pop("registry_connection_id", None)
            return result
        cloud.version.side_effect = version
    with pytest.raises(ValueError):
        prepare_candidate(cloud, plan, "judge", tmp_path)
    cloud.create.assert_not_called()


def test_hosted_default_release_blocks_before_credentials_even_with_execution_flag(plan, monkeypatch, tmp_path):
    import azure.identity
    credential = MagicMock()
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", credential)
    monkeypatch.setenv("EVAL_MODEL_DEPLOYMENT", "judge")
    monkeypatch.chdir(ROOT)
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json())
    assert main(["--plan", str(path), "--output", str(tmp_path / "run"), "--execute-approved-cloud"]) == 1
    decision = json.loads((tmp_path / "run/decision.json").read_text())
    assert decision["status"] == "blocked" and decision["promoted"] is False
    assert len(decision["blockers"]) == 1
    assert "isolated evaluation candidate" in decision["error"]
    credential.assert_not_called()


def test_sdk_serializes_current_hosted_definition(plan):
    project = MagicMock()
    project.agents.create_version.return_value.as_dict.return_value = {"name": plan.agent_name, "version": "4"}
    cloud = FoundryHostedRelease(project, MagicMock())
    cloud.create(plan, {"retained": "metadata"})
    definition = project.agents.create_version.call_args.kwargs["definition"]
    assert definition.container_configuration.image == plan.artifact.image
    assert definition.protocol_versions[0].protocol == "responses"
    assert definition.as_dict() == plan.candidate_definition


def test_real_sdk_hosted_session_and_named_responses_wire_contract(cases, raw, artifact, monkeypatch):
    import time

    import httpx
    from azure.ai.projects import AIProjectClient
    from azure.core.credentials import AccessToken
    from azure.core.pipeline.transport import HttpResponse, HttpTransport

    requests = []

    class Response(HttpResponse):
        def __init__(self, request):
            super().__init__(request, None)
            self.status_code = 201 if request.method == "POST" else 200
            self.headers = {"content-type": "application/json"}
            self.content_type = "application/json"

        def body(self):
            return json.dumps({
                "agent_session_id": "offline-session", "status": "active",
                "version_indicator": {"type": "version_ref", "agent_version": "4"},
                "created_at": 1, "last_accessed_at": 1, "expires_at": 9999999999,
            }).encode()

        def json(self):
            return json.loads(self.body())

    class Transport(HttpTransport):
        def open(self):
            pass

        def close(self):
            pass

        def __exit__(self, *_):
            self.close()

        def send(self, request, **kwargs):
            requests.append(request)
            if request.method == "POST":
                assert request.url.endswith("/agents/documentation-agent/endpoint/sessions?api-version=v1")
                assert json.loads(request.body) == {
                    "version_indicator": {"type": "version_ref", "agent_version": "4"},
                }
            else:
                assert request.method == "GET"
                assert request.url.endswith(
                    "/agents/documentation-agent/endpoint/sessions/offline-session?api-version=v1"
                )
            return Response(request)

    credential = MagicMock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-not-a-credential", int(time.time()) + 3600)

    def respond(request):
        requests.append(request)
        assert request.url.path.endswith("/agents/documentation-agent/endpoint/protocols/openai/responses")
        payload = json.loads(request.content)
        assert payload["agent_session_id"] == "offline-session"
        assert json.loads(payload["input"]) == cases[0]["request"].model_dump(mode="json")
        assert "agent_reference" not in payload
        return httpx.Response(200, json=raw)

    with AIProjectClient(
        endpoint="https://offline.example/api/projects/test", credential=credential, transport=Transport(),
    ) as project:
        factory = project.get_openai_client
        monkeypatch.setattr(project, "get_openai_client", lambda **kwargs: factory(
            **kwargs, api_key="offline-not-a-credential",
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        ))
        report = invoke_hosted(project, cases[0]["request"], "documentation-agent", "4", artifact)
    assert report["agent_session_id"] == "offline-session"
    assert len(requests) == 3


@pytest.mark.parametrize("reference", [
    {"type": "agent_reference", "name": "documentation-agent", "version": "6"},
    {"type": "agent_reference", "name": "another-agent", "version": "7"},
    {"type": "agent_reference", "name": "documentation-agent"},
    {"type": "invalid", "name": "documentation-agent", "version": "7"},
    "invalid",
])
def test_session_get_v7_outer_v6_discrepancy_is_preserved_and_blocks(reference, cases, raw, artifact, capsys):
    raw["agent_reference"] = reference
    project, client = project_for(raw)
    project.agents.create_session.return_value = session(version="7")
    project.agents.get_session.return_value = session(version="7")
    with pytest.raises(ValueError, match="disagrees"):
        invoke_hosted(project, cases[0]["request"], "documentation-agent", "7", artifact)
    diagnostics = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert diagnostics[-1]["session_version_indicator"]["agent_version"] == "7"
    assert diagnostics[-1]["outer_agent_reference"] == reference
    assert diagnostics[-1]["response_id"] == raw["id"]
    assert client.responses.create.call_count == 1
    project.agents.update_details.assert_not_called()


def test_matching_outer_reference_and_session_evidence_are_separate(cases, raw, artifact):
    raw["agent_reference"] = {"type": "agent_reference", "name": "documentation-agent", "version": "4"}
    project, _ = project_for(raw)
    report = invoke_hosted(project, cases[0]["request"], "documentation-agent", "4", artifact)
    assert report["outer_agent_reference"] == raw["agent_reference"]
    assert report["session_version_indicator"] == {"type": "version_ref", "agent_version": "4"}
    assert report["version_evidence"] == "session_get_and_matching_outer_reference"
    assert report["result"]["provenance"]["agent_version"] == "0.4.0"


def test_existing_eval_interface_is_opt_in_not_an_assessment_override(version, artifact):
    from contracts.evaluation import EvaluationRequest

    version["definition"]["environment_variables"].update(
        DOCUMENTATION_MODE="evaluation", DOCUMENTATION_ENABLE_EVALUATION="true",
    )
    with pytest.raises(ValueError, match="assessment"):
        validate_hosted_version(version, artifact, "https://offline.example/api/projects/test", "2026-09-22")
    assert "source_mode" in EvaluationRequest.model_fields


def test_readiness_poll_is_bounded_and_fails_closed(plan, tmp_path, monkeypatch):
    cloud = FoundryHostedRelease(MagicMock(), MagicMock())
    cloud.agent = MagicMock(return_value={
        "name": plan.agent_name, "agent_endpoint": plan.expected_endpoint, "instance_identity": plan.expected_identity,
    })
    cloud.version = MagicMock(return_value={"name": plan.agent_name, "version": "4", "status": "creating"})
    monkeypatch.setattr("tools.hosted_release.time.monotonic", MagicMock(side_effect=[0, 601]))
    with pytest.raises(ValueError, match="timed out"):
        cloud.await_candidate(plan, "4", tmp_path)


@pytest.mark.parametrize("problem", ["metadata", "definition", "after_pin", "invalid_version"])
def test_created_hosted_candidate_never_succeeds_on_readback_drift(problem, plan, cloud, tmp_path):
    if problem == "metadata":
        cloud.await_candidate.return_value["metadata"] = {"changed": "true"}
    elif problem == "definition":
        cloud.await_candidate.return_value["definition"]["memory"] = "8Gi"
    elif problem == "invalid_version":
        cloud.create.return_value["version"] = "latest"
    else:
        changed = deepcopy(cloud.agent.return_value)
        changed["instance_identity"] = {"client_id": "changed"}
        cloud.agent.side_effect = [cloud.agent.return_value, cloud.agent.return_value, changed]
    with pytest.raises(ValueError):
        prepare_candidate(cloud, plan, "judge", tmp_path)
    assert (tmp_path / "candidate.json").exists()
    assert json.loads((tmp_path / "candidate.json").read_text())["promoted"] is False


def test_session_readiness_timeout_never_invokes(cases, raw, artifact, monkeypatch):
    project, client = project_for(raw)
    project.agents.create_session.return_value = session("creating")
    monkeypatch.setattr("tools.hosted.time.monotonic", MagicMock(side_effect=[0, 181]))
    with pytest.raises(ValueError, match="not ready"):
        invoke_hosted(project, cases[0]["request"], "documentation-agent", "4", artifact)
    client.responses.create.assert_not_called()


@pytest.mark.parametrize(
    "problem", ["missing_proof", "stale_proof", "expired", "threshold", "image_tag", "new_environment"]
)
def test_plan_review_requirements_are_not_defaults(problem, plan, cloud, tmp_path):
    data = plan.model_dump()
    if problem == "missing_proof":
        data.pop("serving_path_proof")
    elif problem == "stale_proof":
        data["serving_path_proof"]["observed_at"] = datetime.now(UTC) - timedelta(hours=2)
    elif problem == "expired":
        data["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    elif problem == "threshold":
        data["thresholds"] = {}
    elif problem == "image_tag":
        data["artifact"]["image"] = "offline.azurecr.io/agent:latest"
    else:
        plan.candidate_definition["environment_variables"]["UNREVIEWED_AUTH_SETTING"] = "changed"
        original = cloud.version.side_effect
        def version(name, selected):
            result = original(name, selected)
            result["definition"]["environment_variables"].pop("UNREVIEWED_AUTH_SETTING", None)
            return result
        cloud.version.side_effect = version
        with pytest.raises(ValueError, match="non-runtime"):
            prepare_candidate(cloud, plan, "judge", tmp_path)
        cloud.create.assert_not_called()
        return
    with pytest.raises(ValueError):
        HostedReleasePlan.model_validate(data)


def test_hosted_trigger_validates_before_invocation(plan, version, artifact, raw, cases, tmp_path, monkeypatch, capsys):
    import azure.ai.projects
    import azure.identity
    project, _ = project_for(raw)
    project.__enter__.return_value = project
    project.agents.get_version.return_value = SimpleNamespace(
        name="documentation-agent", version="4", as_dict=lambda: version,
    )
    project.deployments.get.return_value.as_dict.return_value = {"model_version": plan.model_version}
    monkeypatch.setattr(azure.ai.projects, "AIProjectClient", MagicMock(return_value=project))
    monkeypatch.setattr(azure.identity, "AzureCliCredential", MagicMock())
    path = tmp_path / "artifact.json"
    path.write_text(artifact.model_dump_json())
    request = cases[0]["request"]
    assert trigger_main([
        "invoke", "--project-endpoint", plan.project_endpoint, "--artifact", str(path),
        "--agent-version", "4", "--model-version", plan.model_version,
        "--repo", request.subject.repo, "--commit", request.subject.commit_sha,
        "--documentation-standard-ref", request.documentation_standard_ref, "--requested-by", "offline",
        "--request-id", str(request.request_id), "--correlation-id", str(request.correlation_id),
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["agent_version"] == "4" and report["result"]["provenance"] == artifact.runtime_provenance.model_dump()
    project.agents.create_version.assert_not_called()


@pytest.fixture
def evaluation_plan(plan):
    from tools.hosted_release import HostedEvaluationConfig

    plan.evaluation = HostedEvaluationConfig(
        isolation_review_reference="offline-only-review",
        evaluator_deployment="judge", observed_model="offline-model",
        task_scopes={
            "order-sync-retry": "change_review",
            "order-sync-information-missing": "information_review",
            "order-sync-version-isolation": "information_review",
            "order-sync-dead-letter-stub": "information_review",
            "order-sync-wiki-unavailable": "information_review",
        },
    )
    plan.candidate_definition["environment_variables"].update(
        DOCUMENTATION_MODE="evaluation", DOCUMENTATION_ENABLE_EVALUATION="true",
    )
    return HostedReleasePlan.model_validate(plan.model_dump())


def evaluation_raw(case, payload, plan):
    import hashlib
    from uuid import uuid4

    from documentation_agent.read_policy import READ_TOOLS
    from test_release import response_for

    from contracts.evaluation import EvaluationResponse, ExecutionRecord
    from contracts.v1 import AnalysisOutput, assemble_result
    from tools.hosted_evaluation import expected_instructions

    fixture = response_for(case)
    analysis = AnalysisOutput.model_validate_json(fixture["output"][-1]["content"][0]["text"])
    instructions = expected_instructions(plan.candidate_definition, case["mode"])
    provenance = plan.artifact.runtime_provenance.model_copy(update={
        "prompt_version": "sha256:" + hashlib.sha256(instructions.encode()).hexdigest(),
    })
    tools = [item for item in fixture["output"] if item["type"] == "mcp_call"]
    for call in tools:
        if call["server_label"] == "ado":
            args = json.loads(call["arguments"])
            args.update(project="test")
            if call["name"] == "wiki":
                args.update(wikiIdentifier="test.wiki", path="/Order Sync/Overview", includeContent=True)
            else:
                args.update(id=1)
            call["arguments"] = json.dumps(args)
    output = [{
        "type": "function_call", "call_id": call["id"],
        "name": call["server_label"] + "___" + call["name"], "arguments": call["arguments"],
    } for call in tools]
    model_calls = []
    if tools:
        model_calls.append({
            "index": 0, "status": "completed", "response_id": "model-tools-" + case["id"],
            "model": "offline-model", "finish_reason": "tool_calls",
            "input": [{"role": "user", "content": [{"type": "text", "text": payload.request.model_dump_json()}]}],
            "output": [{"role": "assistant", "content": output}],
        })
    model_calls.append({
        "index": len(model_calls), "status": "completed", "response_id": "model-answer-" + case["id"],
        "model": "offline-model", "finish_reason": "stop",
        "input": [{"role": "user", "content": [{"type": "text", "text": payload.model_dump_json()}]}],
        "output": [{"role": "assistant", "content": [{"type": "text", "text": analysis.model_dump_json()}]}],
    })
    if tools:
        model_calls[-1]["input"] = [
            *deepcopy(model_calls[0]["input"]), {"role": "assistant", "content": output},
            *[{"role": "tool", "content": [{
                "type": "function_result", "call_id": call["id"], "result": call["output"],
            }]} for call in tools],
        ]
    report = EvaluationResponse(
        result=assemble_result(payload.request, analysis, provenance),
        execution=ExecutionRecord(
            execution_id=uuid4(), request_id=payload.request.request_id,
            correlation_id=payload.request.correlation_id, source_mode=case["mode"],
            status="completed", instructions=instructions, sources=payload.sources, standard=payload.standard,
            tool_calls=[{key: value for key, value in call.items() if key != "id"} for call in tools],
            tool_schemas=[{"name": name, "description": "Observed offline schema",
                           "parameters": {"type": "object"}} for name in READ_TOOLS] if tools else [],
            model_calls=model_calls,
        ),
    )
    return {
        "id": "outer-" + case["id"], "status": "completed",
        "agent_reference": {"name": plan.agent_name, "version": "4", "type": "agent_reference"},
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": report.model_dump_json()}]}],
    }


def test_all_five_hosted_envelopes_and_observed_scorer_rows(cases, evaluation_plan):
    from tools.hosted_evaluation import evaluation_request, invoke_evaluation

    for case in cases:
        payload = evaluation_request(case, evaluation_plan.evaluation.task_scopes[case["id"]])
        raw = evaluation_raw(case, payload, evaluation_plan)
        project, client = project_for(raw)
        report, row = invoke_evaluation(
            project, case, payload, evaluation_plan.agent_name, "4", evaluation_plan.artifact,
            evaluation_plan.candidate_definition, "offline-model",
        )
        assert row["case_id"] == case["id"]
        sent = client.responses.create.call_args.kwargs
        assert sent["stream"] is False and sent["store"] is False
        assert json.loads(sent["input"]) == payload.model_dump(mode="json")
        assert "reference_answer" not in sent["input"] and "expected_status" not in sent["input"]
        assert payload.request.task.question == case["question"]
        assert report["evaluation"]["result"]["provenance"]["agent_version"] == "0.4.0"
        if case["mode"] == "supplied_sources":
            assert payload.standard.content == case["rules"]
            assert len(payload.sources) == len(case["sources"])
            assert row["tool_calls"] == row["tool_definitions"] == []
        else:
            assert not payload.sources and payload.standard is None and payload.task is None
            assert row["tool_calls"][0]["tool_call_id"] == "call-0"
            assert row["tool_calls"][0]["name"] == "github___get_file_contents"
            # Runtime policy records have no IDs: IDs must come from actual model observations.
            assert "id" not in report["evaluation"]["execution"]["tool_calls"][0]
            assert len(row["tool_definitions"]) == 4


def test_editorial_answers_and_expected_labels_cannot_change_hosted_input(cases):
    from tools.hosted_evaluation import evaluation_request

    for case in cases:
        before = evaluation_request(case, "information_review").model_dump()
        case.update(
            expected_status="arbitrary label", reference_answer="hidden gold",
            input="old prompt bundle containing a reference_answer must never be reused",
        )
        assert evaluation_request(case, "information_review").model_dump() == before


@pytest.mark.parametrize("problem", ["sources", "standard", "tools", "schemas", "attempted_call"])
def test_supplied_evaluation_never_accepts_tool_or_bundle_drift(problem, cases, evaluation_plan):
    import hashlib

    from tools.hosted_evaluation import evaluation_request, invoke_evaluation

    case = cases[2]
    payload = evaluation_request(case, "information_review")
    raw = evaluation_raw(case, payload, evaluation_plan)
    report = json.loads(raw["output"][0]["content"][0]["text"])
    record = report["execution"]
    if problem == "sources":
        record["sources"][0].update(content="drift", sha256=hashlib.sha256(b"drift").hexdigest())
    elif problem == "standard":
        record["standard"].update(content="drift", sha256=hashlib.sha256(b"drift").hexdigest())
    elif problem == "tools":
        record["tool_calls"] = [{"type": "mcp_call"}]
    elif problem == "schemas":
        record["tool_schemas"] = [{"name": "ado___wiki"}]
    else:
        record["model_calls"][0]["output"][0]["content"].insert(
            0, {"type": "function_call", "call_id": "unexpected", "name": "ado___wiki", "arguments": "{}"},
        )
    raw["output"][0]["content"][0]["text"] = json.dumps(report)
    project, _ = project_for(raw)
    with pytest.raises(ValueError):
        invoke_evaluation(
            project, case, payload, evaluation_plan.agent_name, "4", evaluation_plan.artifact,
            evaluation_plan.candidate_definition, "offline-model",
        )


@pytest.mark.parametrize("problem", [
    "correlation", "instructions", "provenance", "incomplete", "no_models", "model_error",
    "model_name", "duplicate_model", "no_schemas", "unknown_schema", "no_calls", "arguments",
    "unknown_call", "missing_id", "duplicate_call_id", "unmatched_result", "refusal", "answer",
    "input_leak", "source_drift", "outer_version", "outer_missing", "platform_session", "wrong_status",
    "model_tool_result", "unsafe_args", "schema", "schema_args",
])
def test_bad_hosted_evidence_never_produces_scorer_row(problem, cases, evaluation_plan):
    from uuid import uuid4

    from tools.hosted_evaluation import evaluation_request, invoke_evaluation

    case = cases[0]
    payload = evaluation_request(case, "change_review")
    raw = evaluation_raw(case, payload, evaluation_plan)
    report = json.loads(raw["output"][0]["content"][0]["text"])
    record = report["execution"]
    if problem == "correlation":
        record["correlation_id"] = str(uuid4())
    elif problem == "instructions":
        record["instructions"] = "unreviewed instructions"
    elif problem == "provenance":
        report["result"]["provenance"]["agent_version"] = "4"
    elif problem == "incomplete":
        record["status"] = "running"
    elif problem == "no_models":
        record["model_calls"] = []
    elif problem == "model_error":
        record["model_calls"][0]["status"] = "failed"
    elif problem == "model_name":
        record["model_calls"][0]["model"] = "unreviewed-model"
    elif problem == "duplicate_model":
        record["model_calls"][1]["response_id"] = record["model_calls"][0]["response_id"]
    elif problem == "no_schemas":
        record["tool_schemas"] = []
    elif problem == "unknown_schema":
        record["tool_schemas"][0]["name"] = "ado___wiki_upsert_page"
    elif problem == "no_calls":
        record["tool_calls"] = []
    elif problem == "arguments":
        record["tool_calls"][0]["arguments"] = "{}"
    elif problem == "unknown_call":
        record["model_calls"][0]["output"][0]["content"][0]["name"] = "ado___wiki_upsert_page"
    elif problem == "missing_id":
        del record["model_calls"][0]["output"][0]["content"][0]["call_id"]
    elif problem == "duplicate_call_id":
        record["model_calls"][0]["output"][0]["content"][1]["call_id"] = "call-0"
    elif problem == "unmatched_result":
        record["tool_calls"].append(deepcopy(record["tool_calls"][0]))
    elif problem == "refusal":
        record["model_calls"][-1]["output"][0]["content"][0]["type"] = "refusal"
    elif problem == "answer":
        answer = json.loads(record["model_calls"][-1]["output"][0]["content"][0]["text"])
        answer["confidence"] = 0.1
        record["model_calls"][-1]["output"][0]["content"][0]["text"] = json.dumps(answer)
    elif problem == "input_leak":
        record["model_calls"][0]["input"][0]["content"][0]["text"] = '{"expected_status":"gaps_found"}'
    elif problem == "source_drift":
        call = record["tool_calls"][0]
        call["output"] = call["output"].replace(case["sources"][0]["content"], "drifted")
        # JSON escaping prevents literal replacement in a serialized source payload.
        call["output"] = '{"documents":[{"content":"drifted"}]}'
        record["model_calls"][-1]["input"][2]["content"][0]["result"] = call["output"]
    elif problem == "model_tool_result":
        record["model_calls"][-1]["input"][2]["content"][0]["result"] = "different from policy output"
    elif problem == "unsafe_args":
        args = json.loads(record["tool_calls"][0]["arguments"])
        args["ref"] = "f" * 40
        record["tool_calls"][0]["arguments"] = json.dumps(args)
        record["model_calls"][0]["output"][0]["content"][0]["arguments"] = json.dumps(args)
    elif problem == "schema":
        record["tool_schemas"][0]["parameters"] = {"type": 2}
    elif problem == "schema_args":
        record["tool_schemas"][1]["parameters"] = {
            "type": "object", "properties": {"owner": {"enum": ["different-owner"]}},
        }
    elif problem == "outer_version":
        raw["agent_reference"]["version"] = "2"
    elif problem == "outer_missing":
        del raw["agent_reference"]
    elif problem == "platform_session":
        record["platform_session_id"] = "another-session"
    else:
        report["result"]["documentation_status"] = "insufficient_information"
        report["result"]["missing_information"] = [{"description": "unknown", "expected_source": "wiki"}]
    raw["output"][0]["content"][0]["text"] = json.dumps(report)
    project, _ = project_for(raw)
    with pytest.raises(ValueError):
        invoke_evaluation(
            project, case, payload, evaluation_plan.agent_name, "4", evaluation_plan.artifact,
            evaluation_plan.candidate_definition, "offline-model",
        )


def evaluation_cloud(cloud, plan):
    from tools.hosted_evaluation import evaluation_request

    original = cloud.version.side_effect
    def version(name, selected):
        result = original(name, selected)
        if selected == plan.serving_version:
            result["definition"]["environment_variables"].update(
                DOCUMENTATION_MODE="assessment", DOCUMENTATION_ENABLE_EVALUATION="false",
            )
        return result
    cloud.version.side_effect = version
    project = MagicMock()
    counter = [0]
    def create_session(**kwargs):
        counter[0] += 1
        return session(session_id=f"session-{counter[0]}")
    project.agents.create_session.side_effect = create_session
    project.agents.get_session.side_effect = lambda **kwargs: session(session_id=kwargs["session_id"])
    def respond(**kwargs):
        sent = json.loads(kwargs["input"])
        case = next(case for case in load_cases(ROOT / "evals/datasets/suite.json", ROOT)[1]
                    if case["request"].subject.commit_sha == sent["request"]["subject"]["commit_sha"]
                    and case["question"] == sent["request"]["task"]["question"])
        # Keep the invocation's fresh request identity, never the separately loaded IDs.
        from contracts.v1 import AgentRequest
        case["request"] = AgentRequest.model_validate(sent["request"])
        payload = evaluation_request(case, plan.evaluation.task_scopes[case["id"]])
        return SimpleNamespace(model_dump=lambda: evaluation_raw(case, payload, plan))
    project.get_openai_client.return_value.__enter__.return_value.responses.create.side_effect = respond
    cloud.project = project
    from test_release import scored_rows
    cloud.evaluate.side_effect = lambda rows, thresholds, *_: scored_rows(len(rows), thresholds)
    return cloud


def test_complete_mocked_hosted_gate_never_promotes(evaluation_plan, cases, cloud, tmp_path):
    from tools.hosted_release import execute

    cloud = evaluation_cloud(cloud, evaluation_plan)
    suite = load_cases(ROOT / "evals/datasets/suite.json", ROOT)[0]
    execute(cloud, evaluation_plan, suite, cases, "judge", tmp_path)
    decision = json.loads((tmp_path / "decision.json").read_text())
    assert decision["status"] == "eligible_for_manual_review" and decision["promoted"] is False
    assert cloud.project.agents.create_session.call_count == 5
    assert cloud.evaluate.call_count == 2
    for call in cloud.evaluate.call_args_list:
        rows, thresholds, _, _, mode = call.args
        assert len(rows) == (2 if mode == "live_sources" else 3)
        assert ("tool_call_accuracy" in thresholds) == (mode == "live_sources")
    cloud.project.agents.update_details.assert_not_called()


@pytest.mark.parametrize("problem", ["eval_error", "missing_score", "bad_score", "serving_eval", "model_drift"])
def test_hosted_gate_blocks_runtime_or_evaluator_failure(problem, evaluation_plan, cases, cloud, tmp_path):
    from test_release import scored_rows

    from tools.hosted_release import execute

    cloud = evaluation_cloud(cloud, evaluation_plan)
    if problem == "eval_error":
        cloud.evaluate.side_effect = ValueError("Evaluator run failed.")
    elif problem in {"missing_score", "bad_score"}:
        def scores(rows, thresholds, *_):
            values = scored_rows(len(rows), thresholds)
            if problem == "missing_score":
                values[0]["results"].pop()
            else:
                values[0]["results"][0]["passed"] = False
            return values
        cloud.evaluate.side_effect = scores
    elif problem == "serving_eval":
        original = cloud.version.side_effect
        def version(name, selected):
            result = original(name, selected)
            result["definition"]["environment_variables"]["DOCUMENTATION_MODE"] = "evaluation"
            return result
        cloud.version.side_effect = version
    else:
        cloud.model_version.side_effect = ["2026-09-22", "judge-version", "changed", "judge-version"]
    suite = load_cases(ROOT / "evals/datasets/suite.json", ROOT)[0]
    with pytest.raises(ValueError):
        execute(cloud, evaluation_plan, suite, cases, "judge", tmp_path)
    assert not (tmp_path / "decision.json").exists()


def test_reviewed_local_preflight_pass_is_not_cloud_certification(evaluation_plan, monkeypatch, tmp_path):
    import azure.identity

    credential = MagicMock()
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", credential)
    monkeypatch.setenv("EVAL_MODEL_DEPLOYMENT", "judge")
    monkeypatch.chdir(ROOT)
    path = tmp_path / "plan.json"
    path.write_text(evaluation_plan.model_dump_json())
    assert main(["--plan", str(path), "--output", str(tmp_path / "run"), "--preflight-only"]) == 0
    decision = json.loads((tmp_path / "run/decision.json").read_text())
    assert decision["status"] == "local_preflight_passed" and decision["cloud_readiness"] == "not_checked"
    credential.assert_not_called()


@pytest.mark.parametrize("failure", [None, "evaluator", "sdk"])
def test_hosted_main_runs_mocked_full_gate_or_persists_blocker(
    failure, evaluation_plan, cloud, monkeypatch, tmp_path,
):
    import azure.ai.projects
    import azure.identity
    from openai import APIConnectionError

    cloud = evaluation_cloud(cloud, evaluation_plan)
    if failure == "evaluator":
        cloud.evaluate.side_effect = ValueError("No completed evaluator results.")
    elif failure == "sdk":
        import httpx
        cloud.evaluate.side_effect = APIConnectionError(request=httpx.Request("POST", "https://offline.example"))
    monkeypatch.setattr("tools.hosted_release.FoundryHostedRelease", MagicMock(return_value=cloud))
    monkeypatch.setattr(azure.ai.projects, "AIProjectClient", MagicMock())
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", MagicMock())
    monkeypatch.setenv("EVAL_MODEL_DEPLOYMENT", "judge")
    monkeypatch.chdir(ROOT)
    path = tmp_path / "plan.json"
    path.write_text(evaluation_plan.model_dump_json())
    code = main(["--plan", str(path), "--output", str(tmp_path / "run"), "--execute-approved-cloud"])
    decision = json.loads((tmp_path / "run/decision.json").read_text())
    assert code == (1 if failure else 0)
    assert decision["status"] == ("blocked" if failure else "eligible_for_manual_review")
    assert decision["promoted"] is False
    if not failure:
        assert decision["promotion_eligible"] is False
    else:
        assert "error" in decision


@pytest.mark.parametrize("problem", ["evaluator_mismatch", "missing_scope", "disabled", "assessment_mode", "no_flag"])
def test_new_preflight_blocks_before_credentials(problem, evaluation_plan, monkeypatch, tmp_path):
    import azure.identity

    credential = MagicMock()
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", credential)
    monkeypatch.setenv("EVAL_MODEL_DEPLOYMENT", "judge")
    monkeypatch.chdir(ROOT)
    if problem == "evaluator_mismatch":
        monkeypatch.setenv("EVAL_MODEL_DEPLOYMENT", "another-judge")
    elif problem == "missing_scope":
        evaluation_plan.evaluation.task_scopes.pop("order-sync-retry")
    elif problem == "disabled":
        evaluation_plan.candidate_definition["environment_variables"]["DOCUMENTATION_ENABLE_EVALUATION"] = "false"
    elif problem == "assessment_mode":
        evaluation_plan.candidate_definition["environment_variables"]["DOCUMENTATION_MODE"] = "assessment"
    path = tmp_path / "plan.json"
    path.write_text(evaluation_plan.model_dump_json())
    argv = ["--plan", str(path), "--output", str(tmp_path / "run")]
    if problem != "no_flag":
        argv.append("--execute-approved-cloud")
    assert main(argv) == 1
    decision = json.loads((tmp_path / "run/decision.json").read_text())
    assert decision["status"] == "blocked" and decision["promoted"] is False
    credential.assert_not_called()


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("case_index", [0, 2])
def test_real_p1_framework_capture_consumes_adapter_without_network(case_index, repair, cases, evaluation_plan):
    import asyncio

    from agent_framework import (
        Agent,
        BaseChatClient,
        ChatMiddlewareLayer,
        ChatResponse,
        Content,
        FunctionInvocationLayer,
        FunctionTool,
        Message,
    )
    from documentation_agent.assessment import AssessmentAgent, run_with_repair
    from documentation_agent.evaluation import EvaluationAgent
    from documentation_agent.execution import CaptureModel
    from documentation_agent.settings import AssessmentSettings

    from contracts.evaluation import EvaluationResponse
    from tools.hosted_evaluation import evaluation_request, evaluator_row, validate_report

    case = cases[case_index]
    payload = evaluation_request(case, evaluation_plan.evaluation.task_scopes[case["id"]])
    fixture = evaluation_raw(case, payload, evaluation_plan)
    prepared = EvaluationResponse.model_validate_json(fixture["output"][0]["content"][0]["text"])
    settings = AssessmentSettings.from_environment(evaluation_plan.candidate_definition["environment_variables"])
    output = prepared.execution.model_calls[-1]["output"][0]["content"][0]["text"]
    fabricated = json.loads(output)
    assert fabricated["evidence"]
    fabricated["evidence"][0]["excerpt"] = "fabricated passage that no source contains"

    class Replay(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.step = 0
            self.answers = 0

        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            self.step += 1
            if self.step == 1 and prepared.execution.tool_calls:
                contents = [
                    Content.from_function_call(
                        f"actual-{index}", call["server_label"] + "___" + call["name"],
                        arguments=json.loads(call["arguments"]),
                    ) for index, call in enumerate(prepared.execution.tool_calls)
                ]
                finish = "tool_calls"
            else:
                self.answers += 1
                bad = repair and self.answers == 1
                contents = [Content.from_text(json.dumps(fabricated) if bad else output)]
                finish = "stop"
            return ChatResponse(
                messages=[Message("assistant", contents)], response_id=f"actual-model-{self.step}",
                model="offline-model", finish_reason=finish,
            )

    class LiveRunner:
        async def analyze(self, request, instructions, guard, check=None):
            record = guard.record
            record.tool_schemas = prepared.execution.tool_schemas
            functions = []
            for call in record.tool_calls if record.tool_calls else prepared.execution.tool_calls:
                def make_function(tool_call):
                    async def tool(**kwargs):
                        return tool_call["output"]
                    return tool
                name = call["server_label"] + "___" + call["name"]
                if not any(function.name == name for function in functions):
                    functions.append(FunctionTool(
                        name=name, func=make_function(call), input_model={"type": "object"},
                    ))
            # Repeated Git calls need distinct source payloads without changing the policy/loop.
            positions = {}
            for function in functions:
                matching = [call for call in prepared.execution.tool_calls
                            if call["server_label"] + "___" + call["name"] == function.name]
                def make_dispatch(name, matches):
                    async def dispatch(**kwargs):
                        index = positions.get(name, 0)
                        positions[name] = index + 1
                        return matches[index]["output"]
                    return dispatch
                function.func = make_dispatch(function.name, matching)
            client = Replay(middleware=[CaptureModel(record)])
            agent = Agent(
                client=client, instructions=instructions, tools=functions, middleware=[guard],
                default_options={"store": False},
            )
            return (await run_with_repair(agent, request.model_dump_json(), check)).text

    class SuppliedRunner:
        async def analyze(self, envelope, record, check=None):
            client = Replay(
                middleware=[CaptureModel(record, tools_disabled=True)],
                function_invocation_configuration={"enabled": False},
            )
            agent = Agent(
                client=client, instructions=record.instructions, tools=[],
                default_options={"store": False, "tool_choice": "none"},
            )
            return (await run_with_repair(agent, envelope.model_dump_json(), check)).text

    runtime = EvaluationAgent(
        settings, live=AssessmentAgent(settings, LiveRunner()), supplied=SuppliedRunner(),
    )
    report = asyncio.run(runtime.evaluate(payload.model_dump_json()))
    raw = deepcopy(fixture)
    raw["output"][0]["content"][0]["text"] = report.model_dump_json()
    checked = validate_report(
        raw, payload, evaluation_plan.artifact, evaluation_plan.candidate_definition,
        {"agent_session_id": "offline-session"}, "offline-model",
    )
    row = evaluator_row(case, payload, checked, evaluation_plan.candidate_definition)
    assert len(row["tool_calls"]) == len(report.execution.tool_calls)
    repair_inputs = [
        call for call in report.execution.model_calls
        if "Verification of your previous AnalysisOutput failed" in json.dumps(call["input"])
    ]
    assert len(repair_inputs) == (1 if repair else 0)
    assert json.loads(report.execution.model_calls[-1]["output"][0]["content"][0]["text"]) == json.loads(output)
