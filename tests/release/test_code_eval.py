"""Synthetic capture replay tests: grader verification, never an agent quality baseline."""

import json
import socket
from copy import deepcopy

import pytest
from test_hosted import (  # Reuse the existing five-case capture doubles, not another corpus.
    artifact,
    cases,
    definition,
    evaluation_plan,
    evaluation_raw,
    plan,
)

from tools.code_eval import CHECKS, ROOT, main
from tools.hosted_evaluation import evaluation_request

# Register the existing pytest fixtures imported above.
__all__ = ["artifact", "cases", "definition", "evaluation_plan", "plan"]


@pytest.fixture(autouse=True)
def no_network_or_judges(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline code evaluation attempted network, credentials, live execution or model judging.")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr("azure.identity.AzureCliCredential", forbidden)
    monkeypatch.setattr("azure.identity.ManagedIdentityCredential", forbidden)
    monkeypatch.setattr("azure.ai.projects.AIProjectClient", forbidden)
    monkeypatch.setattr("tools.release.FoundryEvaluation.evaluate", forbidden)
    monkeypatch.setattr("tools.hosted_release.prepare_candidate", forbidden)
    monkeypatch.setattr("tools.hosted_evaluation.invoke_evaluation", forbidden)


@pytest.fixture
def replay(tmp_path, cases, evaluation_plan):
    captures = tmp_path / "captures"
    captures.mkdir()
    paths = []
    for case in cases:
        payload = evaluation_request(case, evaluation_plan.evaluation.task_scopes[case["id"]])
        outer = evaluation_raw(case, payload, evaluation_plan)
        capture = {
            "run_id": outer["id"], "response_ids": [outer["id"]],
            "agent_name": evaluation_plan.agent_name, "agent_version": "4",
            "agent_session_id": "offline-session-" + case["id"],
            "session_version_indicator": {"type": "version_ref", "agent_version": "4"},
            "outer_agent_reference": outer["agent_reference"],
            "version_evidence": "session_get_and_matching_outer_reference",
            "image": evaluation_plan.artifact.image, "source_commit": evaluation_plan.artifact.source_commit,
            "build_reference": evaluation_plan.artifact.build_reference,
            "request_id": str(payload.request.request_id), "correlation_id": str(payload.request.correlation_id),
            "evaluation": json.loads(outer["output"][0]["content"][0]["text"]),
        }
        path = captures / (case["id"] + "-evaluation.json")
        path.write_text(json.dumps(capture), encoding="utf-8")
        paths.append(path)
    plan_path = tmp_path / "plan.json"
    # Offline replay is not a new live/write approval.
    data = evaluation_plan.model_dump(mode="json")
    data["expires_at"] = "2020-01-01T00:00:00Z"
    data["serving_path_proof"]["observed_at"] = "2020-01-01T00:00:00Z"
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "results" / "baseline.json"
    args = ["--captures", str(captures), "--plan", str(plan_path), "--output", str(output),
            "--evidence-kind", "synthetic"]
    return args, paths, plan_path, output


def change(path, mutate):
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_exact_success_shape_preserves_capture_and_is_repeatable(replay, cases):
    args, paths, _, output = replay
    before = [path.read_bytes() for path in paths]
    assert main(args) == 0
    rows = json.loads(output.read_text())
    assert [row["score"]["case_id"] for row in rows] == [case["id"] for case in cases]
    for row, path in zip(rows, paths, strict=True):
        assert set(row) == {"score", "result"}
        assert row["score"] == {
            "case_id": path.name.removesuffix("-evaluation.json"),
            **dict.fromkeys(CHECKS, True), "passed": True, "error": None,
            "evidence_kind": "synthetic", "suite_sha256": row["score"]["suite_sha256"],
            "plan_sha256": row["score"]["plan_sha256"],
        }
        assert len(row["score"]["suite_sha256"]) == len(row["score"]["plan_sha256"]) == 64
        assert row["result"] == json.loads(path.read_text())
    saved = output.read_bytes()
    assert main(args) == 0
    assert output.read_bytes() == saved
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("problem", ["missing", "malformed", "null", "array", "contract", "duplicate_key", "nan"])
def test_invalid_case_is_a_failure_not_a_skip(replay, problem):
    args, paths, _, output = replay
    if problem == "missing":
        paths[2].unlink()
    elif problem in {"malformed", "null", "array", "duplicate_key", "nan"}:
        paths[2].write_text({
            "malformed": "{", "null": "null", "array": "[]",
            "duplicate_key": '{"evaluation": null, "evaluation": {}}', "nan": '{"evaluation": NaN}',
        }[problem])
    else:
        change(paths[2], lambda data: data["evaluation"]["result"].update(confidence=2))
    assert main(args) == 1
    rows = json.loads(output.read_text())
    failed = rows[2]
    assert len(rows) == 5
    assert failed["result"] is None
    assert all(failed["score"][key] is False for key in (*CHECKS, "passed"))
    assert failed["score"]["error"]
    assert sum(row["score"]["passed"] for row in rows) == 4


@pytest.mark.parametrize("problem,metric", [
    ("status", "status_matches"), ("version", "source_consistent"), ("uri", "source_consistent"),
    ("excerpt", "source_consistent"), ("references", "contract_valid"),
    ("provenance", "execution_valid"), ("source_bundle", "execution_valid"),
    ("model", "execution_valid"), ("tool", "execution_valid"), ("model_tool", "execution_valid"),
    ("no_models", "execution_valid"), ("malformed_model", "execution_valid"),
    ("outer", "execution_valid"), ("session", "execution_valid"),
    ("image", "execution_valid"), ("instructions", "execution_valid"),
    ("answer", "execution_valid"), ("correlation", "execution_valid"),
    ("identity", "execution_valid"), ("incomplete", "execution_valid"),
])
def test_regressions_fail_with_specific_checks(replay, problem, metric):
    args, paths, _, output = replay
    def mutate(data):
        report = data["evaluation"]
        result, record = report["result"], report["execution"]
        if problem == "status":
            result.update(documentation_status="gaps_found", findings=[{
                "category": "synthetic", "severity": "low", "description": "wrong status",
                "evidence_refs": [result["evidence"][0]["id"]],
            }])
        elif problem in {"version", "uri", "excerpt"}:
            result["evidence"][0][problem] = {
                "version": "f" * 40, "uri": "https://example.invalid/fabricated", "excerpt": "fabricated excerpt",
            }[problem]
        elif problem == "references":
            result["evidence"].append(deepcopy(result["evidence"][0]))
        elif problem == "provenance":
            result["provenance"]["model_version"] = "unreviewed"
        elif problem == "source_bundle":
            record["sources"] = []
        elif problem == "model":
            record["model_calls"][0]["model"] = "different-model"
        elif problem == "tool":
            record["tool_calls"] = [{"type": "mcp_call", "name": "wiki_upsert_page"}]
        elif problem == "model_tool":
            record["model_calls"][0]["output"][0]["content"].insert(
                0, {"type": "function_call", "name": "ado___wiki", "call_id": "unexpected", "arguments": "{}"},
            )
        elif problem == "no_models":
            record["model_calls"] = []
        elif problem == "malformed_model":
            record["model_calls"][0] = {}
        elif problem == "outer":
            data["outer_agent_reference"]["version"] = "999"
        elif problem == "session":
            data["session_version_indicator"]["agent_version"] = "999"
        elif problem == "image":
            data["image"] = "different.azurecr.io/image:latest"
        elif problem == "instructions":
            record["instructions"] = "unreviewed"
        elif problem == "answer":
            result["confidence"] = 0.123
        elif problem == "correlation":
            record["correlation_id"] = "00000000-0000-0000-0000-000000000001"
        elif problem == "identity":
            data["request_id"] = "00000000-0000-0000-0000-000000000001"
        elif problem == "incomplete":
            record["status"] = "running"
    change(paths[2], mutate)
    assert main(args) == 1
    row = json.loads(output.read_text())[2]
    assert row["score"][metric] is False
    assert row["score"]["passed"] is False
    assert row["score"]["error"]
    assert (row["result"] is None) == (metric == "contract_valid")


@pytest.mark.parametrize("field", ["run_id", "agent_session_id", "request_id", "execution_id", "model_response_id"])
def test_duplicate_case_execution_fails_both_rows(replay, field):
    args, paths, _, output = replay
    original = json.loads(paths[0].read_text())
    def mutate(data):
        if field == "execution_id":
            data["evaluation"]["execution"][field] = original["evaluation"]["execution"][field]
        elif field == "model_response_id":
            data["evaluation"]["execution"]["model_calls"][0]["response_id"] = (
                original["evaluation"]["execution"]["model_calls"][0]["response_id"]
            )
        else:
            data[field] = original[field]
    change(paths[1], mutate)
    assert main(args) == 1
    rows = json.loads(output.read_text())
    for index in (0, 1):
        assert rows[index]["score"]["passed"] is False
        assert rows[index]["score"]["execution_valid"] is False
        assert "Duplicate" in rows[index]["score"]["error"]


@pytest.mark.parametrize("problem", ["plan", "scope", "artifact", "unknown_case", "suite", "duplicate_suite"])
def test_configuration_errors_exit_two_without_overwriting_report(replay, tmp_path, problem, capsys):
    args, paths, plan_path, output = replay
    output.parent.mkdir()
    output.write_text("previous report")
    if problem == "plan":
        plan_path.write_text("{}")
    elif problem == "scope":
        change(plan_path, lambda data: data["evaluation"]["task_scopes"].pop("order-sync-retry"))
    elif problem == "artifact":
        change(plan_path, lambda data: data["artifact"].update(image="registry.example/image:latest"))
    elif problem == "unknown_case":
        paths[0].with_name("unexpected-evaluation.json").write_text(paths[0].read_text())
    else:
        suite_path = tmp_path / "suite.json"
        suite = json.loads((ROOT / "evals" / "datasets" / "suite.json").read_text())
        if problem == "suite":
            suite["dataset_version"] = "9.0.0"
        else:
            suite["cases"][1] = suite["cases"][0]
        suite_path.write_text(json.dumps(suite))
        args += ["--suite", str(suite_path)]
    assert main(args) == 2
    assert "input/output error" in capsys.readouterr().err
    assert output.read_text() == "previous report"


def test_output_cannot_overwrite_inputs(replay):
    args, paths, _, _ = replay
    original = paths[0].read_bytes()
    assert main([*args, "--output", str(paths[0])]) == 2
    assert paths[0].read_bytes() == original
