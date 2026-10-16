"""Offline mocks only: no credential discovery, live inference or Azure mutation."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from contracts.prompt import OUTPUT_INSTRUCTIONS, structured_format
from tools.release import FoundryRelease, ReleasePlan, execute, gate, main
from tools.release_sources import load_cases

ROOT = Path(__file__).parents[2]


@pytest.fixture
def cases():
    return load_cases(ROOT / "evals/datasets/suite.json", ROOT)


@pytest.fixture
def plan():
    return ReleasePlan(
        project_endpoint="https://offline.example/api/projects/test",
        agent_name="doc-agent",
        base_version="3",
        serving_version="2",
        expected_endpoint={
            "version_selector": {
                "version_selection_rules": [{"type": "FixedRatio", "agent_version": "2", "traffic_percentage": 100}]
            },
            "protocol_configuration": {"responses": {}},
            "authorization_schemes": ["Entra"],
        },
        expected_identity={"client_id": "offline-identity"},
        candidate_definition={
            "kind": "prompt",
            "model": "offline-chat",
            "instructions": OUTPUT_INSTRUCTIONS + "\nReview addition.",
            "tools": [],
            "text": {"format": structured_format()},
        },
        model_version="offline-chat-version",
        eval_model_version="offline-judge-version",
        thresholds={"groundedness": 4, "task_adherence": 1, "tool_call_accuracy": 4},
        approval_reference="offline-test-only",
        writer_hold_reference="offline-test-only",
        evaluator_compatibility_reference="offline-test-only",
        approved_by="unit-test",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def scored_rows(count, thresholds):
    return [
        {
            "datasource_item_id": i,
            "status": "completed",
            "results": [
                {"type": "azure_ai_evaluator", "name": metric, "passed": True, "score": threshold, "label": "pass"}
                for metric, threshold in thresholds.items()
            ],
        }
        for i in range(count)
    ]


def response_for(case):
    source = case["sources"][0]
    analysis = {
        "documentation_status": case["expected_status"],
        "findings": [{"category": "mock", "severity": "low", "description": "mock finding", "evidence_refs": ["e1"]}]
        if case["expected_status"] == "gaps_found"
        else [],
        "proposed_changes": [],
        "missing_information": [{"description": "mock unknown", "expected_source": "unavailable"}]
        if case["expected_status"] == "insufficient_information"
        else [],
        "evidence": [
            {
                "id": "e1",
                "source": source["source"],
                "uri": source["uri"],
                "version": source["version"],
                "excerpt": source["content"][:15],
            }
        ],
        "confidence": 0.5,
        "requires_human_review": True,
    }
    output = []
    if case["mode"] == "live_sources":
        for index, source in enumerate(case["sources"]):
            uri = urlparse(source["uri"])
            if source["source"] == "git":
                parts = uri.path.split("/")
                server, name = "github", "get_file_contents"
                args = {"owner": parts[1], "repo": parts[2], "ref": source["version"], "path": "/".join(parts[5:])}
                payload = {"documents": [{"content": source["content"]}]}
            elif source["source"] == "wiki":
                server, name, args = "ado", "wiki", {"action": "get_page"}
                payload = {
                    "eTag": [source["version"]],
                    "page": {
                        "url": source["uri"],
                        "path": parse_qs(uri.query)["path"][0],
                        "content": source["content"],
                    },
                }
            else:
                server, name, args = "ado", "wit_work_item", {"action": "get"}
                fields = source["content"].split("\n")
                payload = {
                    "rev": int(source["version"]),
                    "url": source["uri"].replace("/_workitems/edit/", "/_apis/wit/workItems/"),
                    "fields": {"System.Title": fields[0], "System.Description": fields[1]},
                }
            output.extend(
                [
                    {
                        "type": "mcp_list_tools",
                        "server_label": server,
                        "tools": [{"name": name, "input_schema": {"type": "object"}}],
                    },
                    {
                        "type": "mcp_call",
                        "status": "completed",
                        "id": f"call-{index}",
                        "server_label": server,
                        "name": name,
                        "arguments": json.dumps(args),
                        "output": json.dumps(payload),
                    },
                ]
            )
        output.append(
            {
                "type": "mcp_call",
                "status": "completed",
                "id": "rules",
                "server_label": "knowledge",
                "name": "knowledge_base_retrieve",
                "arguments": "{}",
                "output": "{}",
            }
        )
        output.insert(
            0,
            {
                "type": "mcp_list_tools",
                "server_label": "knowledge",
                "tools": [{"name": "knowledge_base_retrieve", "input_schema": {"type": "object"}}],
            },
        )
    output.append(
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(analysis)}],
        }
    )
    return {"id": "mock-" + case["id"], "status": "completed", "output": output}


@pytest.fixture
def cloud(plan):
    fake = MagicMock(spec=FoundryRelease)
    fake.agent.return_value = {
        "name": plan.agent_name,
        "agent_endpoint": deepcopy(plan.expected_endpoint),
        "instance_identity": deepcopy(plan.expected_identity),
        "versions": {"latest": {"version": "3"}},
    }
    metadata = {"contract_version": "1.0.0", "policy_version": "1.0.0"}

    def version(name, selected):
        definition = deepcopy(plan.candidate_definition)
        if selected != "4":
            definition["instructions"] = OUTPUT_INSTRUCTIONS
        return {"name": name, "version": selected, "status": "active", "definition": definition, "metadata": metadata}

    fake.version.side_effect = version
    fake.model_version.side_effect = lambda name: (
        plan.model_version if name == "offline-chat" else plan.eval_model_version
    )
    fake.create.return_value = {"name": plan.agent_name, "version": "4"}
    fake.respond.side_effect = lambda case, *_: response_for(case)
    fake.evaluate.side_effect = lambda rows, thresholds, *_: scored_rows(len(rows), thresholds)
    return fake


def test_good_candidate_is_only_eligible_no_promotion(plan, cloud, cases, tmp_path):
    before = deepcopy(cloud.agent.return_value)
    execute(cloud, plan, *cases, "offline-judge", tmp_path)
    decision = json.loads((tmp_path / "decision.json").read_text())
    assert decision["status"] == "eligible_for_manual_review"
    assert decision["promoted"] is False
    assert decision["candidate_version"] == "4" and decision["serving_version"] == "2"
    assert cloud.agent.return_value == before
    assert cloud.create.call_count == 1 and cloud.respond.call_count == 5 and cloud.evaluate.call_count == 2
    live, supplied = cloud.evaluate.call_args_list
    assert len(live.args[0]) == 2 and "tool_call_accuracy" in live.args[1]
    assert len(supplied.args[0]) == 3 and "tool_call_accuracy" not in supplied.args[1]
    result = json.loads((tmp_path / "order-sync-retry-result.json").read_text())
    assert result["result"]["provenance"]["agent_version"] == "4"
    assert result["result"]["provenance"]["model_version"] == plan.model_version
    assert result["run_id"] == "mock-order-sync-retry"
    assert result["correlation_id"] != cases[0]["cases"][0]["request"]["correlation_id"]


def test_bad_candidate_blocks_without_touching_serving(plan, cloud, cases, tmp_path):
    before = deepcopy(cloud.agent.return_value)
    cloud.evaluate.side_effect = lambda rows, thresholds, *_: scored_rows(
        len(rows), {metric: 1 if metric == "groundedness" else threshold for metric, threshold in thresholds.items()}
    )
    with pytest.raises(ValueError, match="Blocking"):
        execute(cloud, plan, *cases, "offline-judge", tmp_path)
    assert not (tmp_path / "decision.json").exists()
    assert (tmp_path / "candidate.json").exists()
    assert cloud.agent.return_value == before


@pytest.mark.parametrize("problem", ["latest", "split", "identity", "judge", "base", "expired", "policy"])
def test_preconditions_fail_before_mutation(problem, plan, cloud, cases, tmp_path):
    if problem == "latest":
        cloud.agent.return_value["agent_endpoint"]["version_selector"]["version_selection_rules"][0][
            "agent_version"
        ] = "@latest"
    elif problem == "split":
        cloud.agent.return_value["agent_endpoint"]["version_selector"]["version_selection_rules"][0][
            "traffic_percentage"
        ] = 50
    elif problem == "identity":
        cloud.agent.return_value["instance_identity"] = {}
    elif problem == "judge":
        cloud.model_version.side_effect = lambda _: "unreviewed"
    elif problem == "base":
        cloud.agent.return_value["versions"]["latest"]["version"] = "9"
    elif problem == "expired":
        plan.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif problem == "policy":
        plan.candidate_definition["instructions"] = "Policy removed"
    with pytest.raises(ValueError):
        execute(cloud, plan, *cases, "offline-judge", tmp_path)
    cloud.create.assert_not_called()
    cloud.respond.assert_not_called()
    cloud.evaluate.assert_not_called()


def test_missing_judge_fails_before_any_cloud_call(plan, cloud, cases, tmp_path):
    with pytest.raises(ValueError, match="EVAL_MODEL_DEPLOYMENT"):
        execute(cloud, plan, *cases, "", tmp_path)
    assert not cloud.mock_calls


@pytest.mark.parametrize(
    "change",
    [
        lambda rows: rows.pop(),
        lambda rows: rows.append(deepcopy(rows[0])),
        lambda rows: rows[0].update(status="failed"),
        lambda rows: rows[0].update(status="skipped"),
        lambda rows: rows[0].update(datasource_item_id="0"),
        lambda rows: rows[0]["results"].pop(),
        lambda rows: rows[0]["results"][0].update(passed=False),
        lambda rows: rows[0]["results"][0].update(label="not_applicable"),
        lambda rows: rows[0]["results"][0].update(status="skipped"),
        lambda rows: rows[0]["results"][0].update(score=float("nan")),
        lambda rows: rows[0]["results"][0].update(score=True),
        lambda rows: rows[0]["results"][0].update(score=0),
    ],
)
def test_incomplete_failed_or_malformed_evaluations_block(change, plan):
    rows = scored_rows(2, plan.thresholds)
    change(rows)
    with pytest.raises(ValueError):
        gate(rows, 2, plan.thresholds)


def test_unset_thresholds_and_expiry_are_not_defaults(plan):
    data = plan.model_dump()
    data["thresholds"] = {}
    with pytest.raises(ValueError, match="thresholds"):
        ReleasePlan.model_validate(data)
    data["thresholds"] = plan.thresholds
    data["expires_at"] = "2000-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="expiry"):
        ReleasePlan.model_validate(data)


def test_adapter_never_leaks_gold_or_cross_case_sources(cases):
    suite, prepared = cases
    for case in prepared:
        original = next(row for row in suite["cases"] if row["id"] == case["id"])
        payload = json.loads(case["input"])
        assert original["reference_answer"] not in case["input"]
        assert "baseline" not in payload and "forbidden_claims" not in payload
        assert len(payload["source_allowlist"]) == len(original["source_ids"])
        if case["mode"] == "supplied_sources":
            assert payload["sources"] == case["sources"]
            assert all(source["source"] == "git" for source in payload["sources"])
        else:
            assert "sources" not in payload


def test_response_adapter_pins_candidate_and_disables_tools(cases):
    client = MagicMock()
    client.responses.create.return_value.model_dump.return_value = {"id": "offline"}
    cloud = FoundryRelease(MagicMock(), client)
    for case in cases[1]:
        cloud.respond(case, "doc-agent", "4")
        kwargs = client.responses.create.call_args.kwargs
        assert kwargs["extra_body"]["agent_reference"]["version"] == "4"
        if case["mode"] == "supplied_sources":
            assert kwargs["tool_choice"] == "none"
        else:
            assert "tool_choice" not in kwargs
        assert "previous_response_id" not in kwargs


@pytest.mark.parametrize("problem", ["drift", "approval", "refusal", "incomplete", "tool_error", "supplied_tool"])
def test_bad_responses_block_before_scoring(problem, plan, cloud, cases, tmp_path):
    def respond(case, *_):
        raw = response_for(case)
        if problem == "drift" and case["mode"] == "live_sources":
            next(item for item in raw["output"] if item["type"] == "mcp_call")["output"] = (
                '{"documents":[{"content":"drift"}]}'
            )
        elif problem == "approval":
            raw["output"].insert(0, {"type": "mcp_approval_request", "id": "no-auto-approval"})
        elif problem == "refusal":
            raw["output"][-1]["content"] = [{"type": "refusal", "refusal": "no"}]
        elif problem == "incomplete":
            raw["status"] = "incomplete"
        elif problem == "tool_error":
            raw["output"].insert(0, {"type": "mcp_call", "error": "read failed"})
        elif problem == "supplied_tool" and case["mode"] == "supplied_sources":
            raw["output"].insert(0, {"type": "mcp_list_tools", "server_label": "bad", "tools": []})
        return raw

    cloud.respond.side_effect = respond
    with pytest.raises(ValueError):
        execute(cloud, plan, *cases, "offline-judge", tmp_path)
    cloud.evaluate.assert_not_called()
    assert all(call.args[2] == "4" for call in cloud.respond.call_args_list)


def test_main_defaults_to_blocked_without_cloud(plan, monkeypatch, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json())
    monkeypatch.setenv("EVAL_MODEL_DEPLOYMENT", "offline-judge")
    monkeypatch.chdir(ROOT)
    output = tmp_path / "result"
    assert main(["--target", "prompt", "--plan", str(path), "--output", str(output)]) == 1
    decision = json.loads((output / "decision.json").read_text())
    assert decision["status"] == "blocked" and decision["promoted"] is False
    assert "execution" in decision["error"]


def test_cloud_evaluation_uses_supported_inline_interface(plan, tmp_path, monkeypatch):
    client = MagicMock()
    client.evals.create.return_value = SimpleNamespace(id="eval-mock", model_dump=lambda: {"id": "eval-mock"})
    client.evals.runs.create.return_value = SimpleNamespace(
        id="run-mock", status="queued", model_dump=lambda: {"id": "run-mock", "status": "queued"}
    )
    client.evals.runs.retrieve.return_value = SimpleNamespace(
        id="run-mock", status="completed", error=None, model_dump=lambda: {"id": "run-mock", "status": "completed"}
    )
    rows = scored_rows(2, plan.thresholds)
    client.evals.runs.output_items.list.return_value = [SimpleNamespace(model_dump=lambda row=row: row) for row in rows]
    monkeypatch.setattr("tools.release.time.sleep", lambda _: None)
    cloud = FoundryRelease(MagicMock(), client)
    actual = cloud.evaluate([{"case_id": "a"}, {"case_id": "b"}], plan.thresholds, "judge", tmp_path, "live")
    gate(actual, 2, plan.thresholds)
    criteria = client.evals.create.call_args.kwargs["testing_criteria"]
    assert {criterion["evaluator_name"] for criterion in criteria} == {"builtin." + name for name in plan.thresholds}
    assert all(criterion["initialization_parameters"]["deployment_name"] == "judge" for criterion in criteria)
    assert client.evals.runs.create.call_args.kwargs["data_source"] == {
        "type": "jsonl",
        "source": {"type": "file_content", "content": [{"item": {"case_id": "a"}}, {"item": {"case_id": "b"}}]},
    }
    client.evals.runs.output_items.list.assert_called_once_with(eval_id="eval-mock", run_id="run-mock")


@pytest.mark.parametrize("status", ["failed", "canceled", "cancelled", "skipped", "incomplete"])
def test_cloud_run_failure_is_not_a_score(status, plan, tmp_path):
    client = MagicMock()
    client.evals.create.return_value = SimpleNamespace(id="eval-mock", model_dump=lambda: {})
    client.evals.runs.create.return_value = SimpleNamespace(
        id="run-mock", status=status, error=None, model_dump=lambda: {"status": status}
    )
    with pytest.raises(ValueError, match="without success"):
        FoundryRelease(MagicMock(), client).evaluate([], plan.thresholds, "judge", tmp_path, "live")
    client.evals.runs.output_items.list.assert_not_called()


def test_bad_main_run_keeps_blocked_artifact_and_serving(plan, cloud, tmp_path, monkeypatch):
    import azure.ai.projects
    import azure.identity

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(azure.ai.projects, "AIProjectClient", MagicMock())
    monkeypatch.setattr("tools.release.FoundryRelease", lambda *_: cloud)
    monkeypatch.setenv("EVAL_MODEL_DEPLOYMENT", "offline-judge")
    monkeypatch.chdir(ROOT)
    cloud.evaluate.return_value = []
    cloud.evaluate.side_effect = None
    before = deepcopy(cloud.agent.return_value)
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json())
    output = tmp_path / "result"
    assert main(["--target", "prompt", "--plan", str(path), "--output", str(output), "--execute-approved-cloud"]) == 1
    decision = json.loads((output / "decision.json").read_text())
    assert decision["status"] == "blocked" and decision["promoted"] is False
    assert "Incomplete" in decision["error"]
    assert cloud.agent.return_value == before
    assert (output / "candidate.json").exists()


def test_real_sdk_serializes_evaluation_payload_offline(plan, tmp_path):
    import httpx
    from azure.ai.projects import AIProjectClient

    requests = []

    def handle(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/evals"):
            body = json.loads(request.content)
            assert body["testing_criteria"][0]["evaluator_name"] == "builtin.groundedness"
            assert body["testing_criteria"][0]["initialization_parameters"]["deployment_name"] == "judge"
            return httpx.Response(200, json={"id": "eval-offline"})
        if path.endswith("/runs"):
            body = json.loads(request.content)
            assert body["data_source"]["source"]["type"] == "file_content"
            return httpx.Response(200, json={"id": "run-offline", "status": "completed", "error": None})
        assert path.endswith("/output_items")
        return httpx.Response(
            200,
            json={
                "object": "list",
                "has_more": False,
                "data": scored_rows(1, plan.thresholds),
            },
        )

    with (
        AIProjectClient(endpoint=plan.project_endpoint, credential=MagicMock()) as project,
        project.get_openai_client(
            api_key="offline-not-a-credential",
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        ) as client,
    ):
        scores = FoundryRelease(project, client).evaluate(
            [{"case_id": "offline"}], plan.thresholds, "judge", tmp_path, "offline"
        )
    gate(scores, 1, plan.thresholds)
    assert len(requests) == 3
    assert all(request.url.host == "offline.example" for request in requests)


def test_preflight_racing_version_writer_blocks_create(plan, cloud, cases, tmp_path):
    changed = deepcopy(cloud.agent.return_value)
    changed["versions"]["latest"]["version"] = "4"
    cloud.agent.side_effect = [cloud.agent.return_value, changed]
    with pytest.raises(ValueError, match="Another writer"):
        execute(cloud, plan, *cases, "offline-judge", tmp_path)
    cloud.create.assert_not_called()


def test_post_create_serving_drift_blocks_invocation(plan, cloud, cases, tmp_path):
    original = deepcopy(cloud.agent.return_value)
    changed = deepcopy(original)
    changed["agent_endpoint"]["version_selector"]["version_selection_rules"][0]["agent_version"] = "@latest"
    cloud.agent.side_effect = [original, original, changed]
    with pytest.raises(ValueError, match="configuration"):
        execute(cloud, plan, *cases, "offline-judge", tmp_path)
    cloud.create.assert_called_once()
    cloud.respond.assert_not_called()


def test_changed_candidate_readback_blocks_invocation(plan, cloud, cases, tmp_path):
    original = cloud.version.side_effect

    def changed(name, selected):
        version = original(name, selected)
        if selected == "4":
            version["definition"]["model"] = "wrong-deployment"
        return version

    cloud.version.side_effect = changed
    with pytest.raises(ValueError, match="readback"):
        execute(cloud, plan, *cases, "offline-judge", tmp_path)
    cloud.respond.assert_not_called()


def test_model_upgrade_during_run_blocks_eligibility(plan, cloud, cases, tmp_path):
    original = cloud.model_version.side_effect

    def upgrade(name):
        if cloud.evaluate.call_count:
            return "upgraded-mid-run"
        return original(name)

    cloud.model_version.side_effect = upgrade
    with pytest.raises(ValueError, match="model deployment version changed"):
        execute(cloud, plan, *cases, "offline-judge", tmp_path)
    assert not (tmp_path / "decision.json").exists()


def test_snapshot_and_rules_drift_block_loading(cases, tmp_path):
    import shutil

    datasets = tmp_path / "datasets"
    shutil.copytree(ROOT / "evals/datasets", datasets)
    (datasets / "fixtures/base-settings.json").write_text("changed")
    with pytest.raises(ValueError, match="snapshot drift"):
        load_cases(datasets / "suite.json", ROOT)
    suite = deepcopy(cases[0])
    suite["documentation_standard"]["git_blob_sha"] = "wrong"
    (datasets / "suite.json").write_text(json.dumps(suite))
    with pytest.raises(ValueError, match="standard has drifted"):
        load_cases(datasets / "suite.json", ROOT)
