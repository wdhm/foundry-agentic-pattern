import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from contracts import CONTRACT_VERSION, AgentRequest, AgentResult
from contracts.generate_schema import generate_schemas

SCHEMA_DIR = Path(__file__).parents[2] / "src" / "contracts" / "schema"


@pytest.fixture
def request_payload():
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": "806c4972-cfcc-4f27-9900-059a22233179",
        "correlation_id": "70e295ec-dd1f-4946-859e-64836e458d94",
        "trigger": "cli",
        "requested_by": "demo-reviewer",
        "subject": {
            "repo": "example/sample-integration",
            "commit_sha": "a" * 40,
            "changed_paths": ["samples/sample-integration/config.json"],
        },
        "documentation_standard_ref": "data/documentation-standard.md",
    }


@pytest.fixture
def result_payload(request_payload):
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": request_payload["request_id"],
        "provenance": {
            "agent_name": "documentation-agent",
            "agent_version": "1",
            "model": "demo-chat",
            "model_version": "demo-version",
            "prompt_version": "0.1.0",
            "policy_version": "0.1.0",
            "contract_version": CONTRACT_VERSION,
        },
    }


def schema_validator(model):
    schema = json.loads((SCHEMA_DIR / f"{model.__name__}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("model,fixture_name", [(AgentRequest, "request_payload"), (AgentResult, "result_payload")])
def test_validation_and_json_round_trip(model, fixture_name, request):
    payload = request.getfixturevalue(fixture_name)
    parsed = model.model_validate_json(json.dumps(payload))
    assert isinstance(parsed.request_id, UUID)
    assert model.model_validate_json(parsed.model_dump_json()) == parsed
    schema_validator(model).validate(payload)
    schema_validator(model).validate(parsed.model_dump(mode="json"))


def test_context_and_trigger_are_adapter_agnostic(request_payload):
    request_payload["trigger"] = "scheduled_scan"
    request_payload["subject"]["pr_reference"] = "https://github.com/example/sample-integration/pull/1"
    request_payload["context"] = {
        "wiki_page_paths": ["/integration"],
        "work_item_ids": [42],
        "adr_refs": ["docs/adr/0001.md"],
    }
    parsed = AgentRequest.model_validate(request_payload)
    assert parsed.trigger == "scheduled_scan"
    assert parsed.context.work_item_ids == [42]
    schema_validator(AgentRequest).validate(request_payload)


@pytest.mark.parametrize(
    "path,value",
    [
        (("contract_version",), "1.0.0"),
        (("request_id",), "not-a-uuid"),
        (("correlation_id",), "not-a-uuid"),
        (("trigger",), " "),
        (("requested_by",), ""),
        (("subject", "repo"), " "),
        (("subject", "commit_sha"), "abc123"),
        (("subject", "commit_sha"), "g" * 40),
        (("subject", "changed_paths"), [""]),
        (("subject", "pr_reference"), ""),
        (("documentation_standard_ref",), " "),
        (("unexpected",), True),
        (("subject", "unexpected"), True),
        (("context",), {"work_item_ids": [0]}),
        (("context",), {"work_item_ids": [True]}),
        (("context",), {"work_item_ids": ["42"]}),
        (("context",), {"wiki_page_paths": [" "]}),
        (("context",), {"adr_refs": [""]}),
        (("context",), {"unexpected": True}),
    ],
)
def test_invalid_request_rejected_by_python_and_schema(request_payload, path, value):
    parent = request_payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValidationError):
        AgentRequest.model_validate_json(json.dumps(request_payload))
    assert not schema_validator(AgentRequest).is_valid(request_payload)


@pytest.mark.parametrize("field", [field for field in AgentRequest.model_fields if field != "context"])
def test_required_request_fields(request_payload, field):
    del request_payload[field]
    with pytest.raises(ValidationError):
        AgentRequest.model_validate(request_payload)
    assert not schema_validator(AgentRequest).is_valid(request_payload)


@pytest.mark.parametrize(
    "field",
    ["agent_name", "agent_version", "model", "model_version", "prompt_version", "policy_version", "contract_version"],
)
def test_provenance_fields_are_required(result_payload, field):
    del result_payload["provenance"][field]
    with pytest.raises(ValidationError):
        AgentResult.model_validate(result_payload)
    assert not schema_validator(AgentResult).is_valid(result_payload)


@pytest.mark.parametrize(
    "field",
    ["agent_name", "agent_version", "model", "model_version", "prompt_version", "policy_version", "contract_version"],
)
def test_invalid_provenance_rejected(result_payload, field):
    result_payload["provenance"][field] = " "
    with pytest.raises(ValidationError):
        AgentResult.model_validate(result_payload)
    assert not schema_validator(AgentResult).is_valid(result_payload)


@pytest.mark.parametrize("field", ["contract_version", "request_id", "provenance"])
def test_required_result_fields(result_payload, field):
    del result_payload[field]
    with pytest.raises(ValidationError):
        AgentResult.model_validate(result_payload)
    assert not schema_validator(AgentResult).is_valid(result_payload)


@pytest.mark.parametrize(
    "path,value",
    [
        (("contract_version",), "1.0.0"),
        (("request_id",), "not-a-uuid"),
        (("unexpected",), True),
        (("provenance", "unexpected"), True),
        (("provenance", "contract_version"), "1.0.0"),
    ],
)
def test_invalid_result_rejected_by_python_and_schema(result_payload, path, value):
    parent = result_payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValidationError):
        AgentResult.model_validate_json(json.dumps(result_payload))
    assert not schema_validator(AgentResult).is_valid(result_payload)


def test_mutable_defaults_are_isolated(request_payload):
    first = AgentRequest.model_validate(request_payload)
    second = AgentRequest.model_validate(deepcopy(request_payload))
    first.context.work_item_ids.append(42)
    assert second.context.work_item_ids == []
    first.subject.changed_paths.append("extra.py")
    assert second.subject.changed_paths == request_payload["subject"]["changed_paths"]


def test_committed_schemas_match_models():
    assert generate_schemas(SCHEMA_DIR, check=True)


def test_schema_generation_is_deterministic_and_detects_drift(tmp_path):
    assert not generate_schemas(tmp_path, check=True)
    assert generate_schemas(tmp_path)
    first = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert generate_schemas(tmp_path)
    assert first == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert generate_schemas(tmp_path, check=True)
    path = tmp_path / "AgentRequest.schema.json"
    path.write_text("{}\n", encoding="utf-8")
    assert not generate_schemas(tmp_path, check=True)
    assert path.read_text(encoding="utf-8") == "{}\n"
