import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from contracts.evaluation import EvaluationRequest
from contracts.v1 import AgentRequest, AnalysisOutput, AssessmentTask, Provenance, assemble_result

ROOT = Path(__file__).parents[2]


@pytest.fixture
def payload():
    return json.loads((ROOT / "src/contracts/examples/request-v1.json").read_text())


@pytest.mark.parametrize(
    "task",
    [
        {},
        {"scope": "arbitrary", "question": "Assess"},
        {"scope": "change_review", "question": ""},
        {"scope": "information_review", "question": "   "},
        {"scope": "information_review", "question": "x" * 8001},
        {"scope": "information_review", "question": 123},
        {"scope": "information_review", "question": "Assess", "approved": True},
    ],
)
def test_invalid_tasks_are_rejected_by_models_and_schema(payload, task):
    payload["task"] = task
    with pytest.raises(ValidationError):
        AgentRequest.model_validate(payload)
    assert not Draft202012Validator(AgentRequest.model_json_schema()).is_valid(payload)


def test_legacy_and_null_task_are_supported(payload):
    legacy = AgentRequest.model_validate(payload)
    assert legacy.task is None
    assert "task" not in json.loads(legacy.model_dump_json())
    assert "task" not in legacy.model_dump(mode="json")
    payload["task"] = None
    parsed = AgentRequest.model_validate(payload)
    assert parsed.task is None
    assert "task" not in parsed.model_dump()
    Draft202012Validator(AgentRequest.model_json_schema()).validate(payload)


def test_change_review_needs_paths_but_information_review_does_not(payload):
    payload["subject"]["changed_paths"] = []
    payload["task"] = {"scope": "change_review", "question": "Assess the change"}
    with pytest.raises(ValidationError, match="changed_paths"):
        AgentRequest.model_validate(payload)
    payload["task"]["scope"] = "information_review"
    AgentRequest.model_validate(payload)


@pytest.mark.parametrize("scope", ["change_review", "information_review"])
def test_task_roundtrip_and_length_boundary(payload, scope):
    payload["task"] = {"scope": scope, "question": "x" * 8000}
    request = AgentRequest.model_validate_json(json.dumps(payload))
    assert AgentRequest.model_validate_json(request.model_dump_json()) == request
    Draft202012Validator(AgentRequest.model_json_schema()).validate(request.model_dump(mode="json"))


def test_live_evaluation_carries_task_inside_request_without_outer_override(payload):
    payload["task"] = {"scope": "information_review", "question": "Identify business owner"}
    envelope = {"interface_version": "1.0.0", "source_mode": "live_sources", "request": payload}
    request = EvaluationRequest.model_validate(envelope)
    assert request.request.task.question == payload["task"]["question"]
    envelope["task"] = "Another task"
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(envelope)


def test_supplied_evaluation_rejects_conflicting_task(payload):
    payload["task"] = {"scope": "information_review", "question": "Identify business owner"}
    with pytest.raises(ValidationError, match="conflicts"):
        EvaluationRequest.model_validate(
            {
                "interface_version": "1.0.0",
                "source_mode": "supplied_sources",
                "request": payload,
                "task": "Review timeout",
            }
        )


def test_explicit_task_status_is_validated_not_silently_rewritten(payload):
    request = AgentRequest.model_validate(payload)
    output = AnalysisOutput(
        documentation_status="gaps_found",
        findings=[
            {
                "category": "operations",
                "severity": "medium",
                "description": "Runbook missing",
                "evidence_refs": ["source"],
            }
        ],
        proposed_changes=[],
        missing_information=[{"description": "Runbook location unavailable", "expected_source": "wiki"}],
        evidence=[
            {
                "id": "source",
                "source": "git",
                "uri": "https://example.com/config",
                "version": "a" * 40,
                "excerpt": "sample",
            }
        ],
        confidence=0.5,
        requires_human_review=True,
    )
    provenance = Provenance(
        agent_name="test",
        agent_version="test",
        model="test",
        model_version="test",
        prompt_version="test",
        policy_version="test",
        contract_version="1.0.0",
    )
    # Previously accepted v1 output stays accepted for legacy requests.
    assemble_result(request, output, provenance)
    request.task = AssessmentTask(scope="information_review", question="Identify runbook")
    with pytest.raises(ValueError, match="Unresolved information"):
        assemble_result(request, output, provenance)
    assert output.documentation_status == "gaps_found"
    output.documentation_status = "insufficient_information"
    assert assemble_result(request, output, provenance).documentation_status == "insufficient_information"


@pytest.mark.parametrize(
    "example,scenario,scope",
    [
        ("assessment-request.json", "order-sync-retry", "change_review"),
        ("information-review-request.json", "order-sync-information-missing", "information_review"),
    ],
)
def test_examples_preserve_original_scenario_question_and_sources(example, scenario, scope):
    sample = AgentRequest.model_validate_json((ROOT / "src/agents/documentation-agent/examples" / example).read_text())
    original = json.loads((ROOT / "evals/datasets" / f"{scenario}.json").read_text())
    assert sample.task.question == original["prompt"]
    assert sample.task.scope == scope
    assert sample.subject.commit_sha == original["subject"]["commit_sha"]
    assert sample.context.wiki_page_paths == original["context"]["wiki_page_paths"]
    assert sample.context.work_item_ids == original["context"]["work_item_ids"]
