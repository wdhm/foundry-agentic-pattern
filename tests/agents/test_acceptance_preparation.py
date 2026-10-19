import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from documentation_agent.acceptance import CASES, extract, prepare, response_json

from contracts.v1 import AgentRequest, AgentResult, AnalysisOutput

ROOT = Path(__file__).parents[2]


def test_preparation_preserves_canonical_input_and_fresh_ids(tmp_path):
    first = prepare(ROOT, tmp_path / "first", 42)
    second = prepare(ROOT, tmp_path / "second", 42)
    assert first["state"] == "prepared_not_run"
    assert first["agent_version"] == 42
    suite = json.loads((ROOT / "evals/datasets/suite.json").read_text())
    ids = []
    for index, (case_id, _, scope) in enumerate(CASES):
        generated = first["cases"][index]
        original = next(case for case in suite["cases"] if case["id"] == case_id)
        payload = json.loads((tmp_path / "first" / generated["request"]).read_text())
        sample = AgentRequest.model_validate(payload)
        assert sample.task.scope == scope
        scenario = json.loads((ROOT / generated["scenario"]).read_text())
        assert sample.task.question == scenario["prompt"]
        assert generated["expected_status"] == scenario["expected_status"]
        for field in ("subject", "context", "documentation_standard_ref", "trigger", "requested_by"):
            assert payload[field] == AgentRequest.model_validate(original["request"]).model_dump(mode="json")[field]
        ids.extend([generated["request_id"], generated["correlation_id"]])
        assert generated["request_id"] != second["cases"][index]["request_id"]
        assert "\n" not in (tmp_path / "first" / generated["request"]).read_text()
    assert len(set(ids)) == 4
    for value in ids:
        UUID(value)
    with pytest.raises(ValueError, match="new output directory"):
        prepare(ROOT, tmp_path / "first", 42)
    assert json.loads((tmp_path / "first/manifest.json").read_text()) == first


@pytest.mark.parametrize("drift", ["question", "subject", "context"])
def test_preparation_fails_before_writing_when_sources_or_questions_drift(tmp_path, drift):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "evals/datasets", repo / "evals/datasets")
    examples = repo / "src/agents/documentation-agent/examples"
    shutil.copytree(ROOT / "src/agents/documentation-agent/examples", examples)
    path = examples / "assessment-request.json"
    data = json.loads(path.read_text())
    if drift == "question":
        data["task"]["question"] = "Different task"
    elif drift == "subject":
        data["subject"]["commit_sha"] = "b" * 40
    else:
        data["context"]["wiki_page_paths"] = ["/different"]
    path.write_text(json.dumps(data))
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        prepare(repo, output, 42)
    assert not output.exists()


@pytest.fixture
def response_pair():
    request = AgentRequest.model_validate_json(
        (ROOT / "src/agents/documentation-agent/examples/information-review-request.json").read_text()
    )
    result = {
        "contract_version": "1.0.0",
        "request_id": str(request.request_id),
        "documentation_status": "insufficient_information",
        "findings": [],
        "proposed_changes": [],
        "missing_information": [{"description": "Test unknown", "expected_source": "wiki"}],
        "evidence": [],
        "confidence": 0,
        "requires_human_review": True,
        "provenance": {
            "agent_name": "documentation-agent",
            "agent_version": "0.4.0",
            "model": "test",
            "model_version": "test",
            "prompt_version": "test",
            "policy_version": "test",
            "contract_version": "1.0.0",
        },
    }
    AgentResult.model_validate(result)
    return request, {
        "id": "test-response",
        "status": "completed",
        "output": [
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(result)}]}
        ],
    }


def test_extract_json_and_sse_without_claiming_quality(response_pair):
    request, raw = response_pair
    assert response_json(json.dumps(raw)) == raw
    sse = "CLI log\n" + "data: " + json.dumps({"type": "response.completed", "response": raw}) + "\n\ndata: [DONE]\n"
    result = extract(request, response_json(sse), "0.4.0")
    assert result.missing_information[0].description == "Test unknown"
    assert result.request_id == request.request_id


@pytest.mark.parametrize(
    "bad", ["failed", "request", "version", "agent", "approval", "duplicate", "refusal", "no_task"]
)
def test_extraction_rejects_wrong_or_incomplete_results(response_pair, bad):
    request, raw = response_pair
    result = json.loads(raw["output"][0]["content"][0]["text"])
    if bad == "failed":
        raw["status"] = "failed"
    elif bad == "request":
        result["request_id"] = str(uuid4())
    elif bad == "version":
        result["provenance"]["agent_version"] = "0.3.0"
    elif bad == "agent":
        result["provenance"]["agent_name"] = "doc-agent"
    elif bad == "duplicate":
        raw["output"].append(raw["output"][0])
    elif bad == "approval":
        raw["output"][0]["type"] = "mcp_approval_request"
    elif bad == "refusal":
        raw["output"][0]["content"][0]["type"] = "refusal"
    else:
        request.task = None
    raw["output"][0]["content"][0]["text"] = json.dumps(result)
    with pytest.raises(ValueError):
        extract(request, raw, "0.4.0")


def test_sse_failure_or_multiple_completions_rejected(response_pair):
    _, raw = response_pair
    completion = "data: " + json.dumps({"type": "response.completed", "response": raw}) + "\n"
    for text in [
        completion * 2,
        'data: {"type":"response.failed"}\n' + completion,
        "no completion",
        "data: null\n",
    ]:
        with pytest.raises(ValueError):
            response_json(text)


def test_cli_prepares_and_extracts_checker_compatible_analysis(tmp_path, response_pair):
    request, raw = response_pair
    prep = subprocess.run(
        [
            sys.executable, "-m", "documentation_agent.acceptance", "prepare",
            "--repo-root", str(ROOT), "--output-dir", str(tmp_path / "prepared"), "--agent-version", "42",
        ],
        capture_output=True,
        text=True,
    )
    assert prep.returncode == 0, prep.stderr
    assert "not invoked" in prep.stdout
    request_file = tmp_path / "request.json"
    response_file = tmp_path / "response.txt"
    request_file.write_text(request.model_dump_json(), encoding="utf-8")
    response_file.write_text(json.dumps(raw), encoding="utf-8")
    command = [
        sys.executable, "-m", "documentation_agent.acceptance", "extract",
        "--request", str(request_file), "--response", str(response_file),
        "--output", str(tmp_path / "result.json"), "--analysis-output", str(tmp_path / "analysis.json"),
        "--expected-app-version", "0.4.0",
    ]
    extracted = subprocess.run(command, capture_output=True, text=True)
    assert extracted.returncode == 0, extracted.stderr
    analysis = AnalysisOutput.model_validate_json((tmp_path / "analysis.json").read_text())
    assert analysis.documentation_status == "insufficient_information"
    assert "provenance" not in json.loads((tmp_path / "analysis.json").read_text())
    repeated = subprocess.run(command, capture_output=True, text=True)
    assert repeated.returncode != 0
    assert "overwrite" in repeated.stderr
