import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from contracts import AgentRequest as StubRequest
from contracts.prompt import OUTPUT_INSTRUCTIONS, configured_definition, structured_format, validate_response
from contracts.v1 import AgentRequest, AgentResult, AnalysisOutput, Provenance, assemble_result


@pytest.fixture
def agent_request():
    return AgentRequest.model_validate_json(
        (Path(__file__).parents[2] / "src/contracts/examples/request-v1.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def provenance():
    return Provenance(
        contract_version="1.0.0",
        agent_name="example-agent",
        agent_version="3",
        model="example-chat",
        model_version="example-version",
        prompt_version="example-prompt",
        policy_version="1.0.0",
    )


@pytest.fixture
def analysis():
    return {
        "documentation_status": "gaps_found",
        "findings": [
            {
                "category": "configuration",
                "severity": "medium",
                "description": "Retry limit missing.",
                "evidence_refs": ["code"],
            }
        ],
        "proposed_changes": [
            {
                "target_page": "/integration",
                "target_section": "Retries",
                "proposed_content": "Retry limit is 3.",
                "evidence_refs": ["code"],
            }
        ],
        "missing_information": [],
        "evidence": [
            {
                "id": "code",
                "source": "git",
                "uri": "https://example.com/repo/config",
                "version": "a" * 40,
                "excerpt": "retry_limit = 3",
            }
        ],
        "confidence": 0.8,
        "requires_human_review": True,
    }


def test_complete_result_roundtrip_and_schema(agent_request, provenance, analysis):
    result = assemble_result(agent_request, AnalysisOutput.model_validate(analysis), provenance)
    assert AgentResult.model_validate_json(result.model_dump_json()) == result
    assert result.request_id == agent_request.request_id
    assert result.provenance == provenance
    schema = AgentResult.model_json_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))


@pytest.mark.parametrize("field", list(AnalysisOutput.model_fields))
def test_every_analysis_field_required(analysis, field):
    del analysis[field]
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("field", ["findings", "proposed_changes"])
def test_references_must_resolve(analysis, field):
    analysis[field][0]["evidence_refs"] = ["not-present"]
    with pytest.raises(ValidationError, match="resolve"):
        AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("field", ["findings", "proposed_changes"])
def test_references_cannot_be_empty(analysis, field):
    analysis[field][0]["evidence_refs"] = []
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


def test_duplicate_evidence_ids_rejected(analysis):
    analysis["evidence"].append(deepcopy(analysis["evidence"][0]))
    with pytest.raises(ValidationError, match="unique"):
        AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("version", ["", " ", "main", "latest", "abc123", "g" * 40])
def test_git_evidence_requires_exact_version(analysis, version):
    analysis["evidence"][0]["version"] = version
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("source,version", [("wiki", '"etag-42"'), ("work_item", "3")])
def test_other_exact_versions_accepted(analysis, source, version):
    analysis["evidence"][0].update(source=source, version=version)
    AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("source,version", [("wiki", "latest"), ("work_item", "0"), ("work_item", "1.2")])
def test_other_unversioned_sources_rejected(analysis, source, version):
    analysis["evidence"][0].update(source=source, version=version)
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("nan"), float("inf"), True, "0.8"])
def test_confidence_bounds(analysis, confidence):
    analysis["confidence"] = confidence
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("confidence", [0, 1])
def test_confidence_endpoints(analysis, confidence):
    analysis["confidence"] = confidence
    AnalysisOutput.model_validate(analysis)


def test_changes_require_review(analysis):
    analysis["requires_human_review"] = False
    with pytest.raises(ValidationError, match="human review"):
        AnalysisOutput.model_validate(analysis)


@pytest.mark.parametrize("status", ["up_to_date", "insufficient_information"])
def test_inconsistent_status_rejected(analysis, status):
    analysis["documentation_status"] = status
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


def test_up_to_date_requires_evidence(analysis):
    analysis.update(documentation_status="up_to_date", findings=[], proposed_changes=[])
    AnalysisOutput.model_validate(analysis)
    analysis["evidence"] = []
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


def test_v0_request_is_not_silently_upgraded(agent_request):
    payload = agent_request.model_dump(mode="json")
    with pytest.raises(ValidationError):
        StubRequest.model_validate(payload)
    payload["contract_version"] = "0.1.0"
    StubRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        AgentRequest.model_validate(payload)


def test_native_schema_has_all_fields_required():
    schema = structured_format()
    assert schema["strict"] is True
    for model in [schema["schema"], *schema["schema"]["$defs"].values()]:
        assert model["additionalProperties"] is False
        assert set(model["properties"]) == set(model["required"])


def test_configuration_preserves_tools_model_approvals_and_source():
    definition = {
        "kind": "prompt",
        "model": "existing-model",
        "instructions": "Existing instructions.",
        "reasoning": {"effort": "low"},
        "tools": [{"type": "mcp", "require_approval": "always", "server_url": "https://example.com/mcp"}],
    }
    original = deepcopy(definition)
    configured = configured_definition(definition)
    assert definition == original
    for key in ("model", "tools", "reasoning"):
        assert configured[key] == original[key]
    assert configured["instructions"].startswith(original["instructions"])
    assert configured["instructions"].count(OUTPUT_INSTRUCTIONS) == 1
    assert configured["text"]["format"] == structured_format()
    assert configured_definition(configured) == configured


def test_hosted_definition_cannot_be_reconfigured():
    with pytest.raises(ValueError, match="prompt agent"):
        configured_definition({"kind": "hosted"})


def test_configuration_preserves_p2_tools_and_later_grounding_instructions():
    grounding = (
        "Use knowledge_base_retrieve before assessing documentation. "
        "Cite DS-xx rule IDs. The standard is a rule set, not evidence: "
        "don't add it to the evidence array."
    )
    definition = {
        "kind": "prompt",
        "model": "existing-model",
        "instructions": "Existing instructions.\n\n" + OUTPUT_INSTRUCTIONS + "\n\n" + grounding,
        "reasoning": {"effort": "low"},
        "text": {"format": structured_format()},
        "tools": [
            {
                "type": "mcp",
                "server_label": "knowledge",
                "server_url": "https://example.com/knowledge/mcp",
                "project_connection_id": "kb-doc-agent-mcp",
                "allowed_tools": ["knowledge_base_retrieve"],
                "require_approval": "never",
            },
            {
                "type": "mcp",
                "server_label": "github",
                "server_url": "https://example.com/github/mcp",
                "project_connection_id": "github-mcp",
                "require_approval": "never",
            },
            {
                "type": "mcp",
                "server_label": "ado",
                "server_url": "https://example.com/ado/mcp",
                "project_connection_id": "ado-mcp-proxy",
                "require_approval": {"always": {"tool_names": ["wiki_upsert_page"]}},
            },
        ],
    }
    original = deepcopy(definition)
    assert configured_definition(definition) == original
    # Attaching a missing schema must also preserve all newer tools and instruction text.
    del definition["text"]
    updated = configured_definition(definition)
    assert updated == original
    assert "text" not in definition


def test_standard_rule_ids_do_not_require_a_new_evidence_source(analysis):
    analysis["findings"][0]["description"] = "DS-14: Retry limit is missing from the documentation."
    result = AnalysisOutput.model_validate(analysis)
    assert result.findings[0].description.startswith("DS-14")
    assert {item.source for item in result.evidence} == {"git"}
    analysis["evidence"][0]["source"] = "knowledge"
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(analysis)


def unknown_analysis():
    return {
        "documentation_status": "insufficient_information",
        "findings": [],
        "proposed_changes": [],
        "missing_information": [{"description": "Source content not available.", "expected_source": "repository"}],
        "evidence": [],
        "confidence": 0,
        "requires_human_review": True,
    }


def response_for(output):
    return {
        "status": "completed",
        "output": [
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(output)}]}
        ],
    }


def test_native_response_is_validated_and_metadata_supplied_by_caller(agent_request, provenance):
    result = validate_response(response_for(unknown_analysis()), agent_request, provenance)
    assert result.provenance == provenance
    assert result.request_id == agent_request.request_id


def test_no_tools_demo_rejects_invented_evidence(analysis, agent_request, provenance):
    with pytest.raises(ValueError, match="without reading sources"):
        validate_response(response_for(analysis), agent_request, provenance)


def test_tool_discovery_is_not_tool_execution(agent_request, provenance):
    response = response_for(unknown_analysis())
    response["output"].insert(0, {"type": "mcp_list_tools", "tools": []})
    validate_response(response, agent_request, provenance)
    response["output"][0] = {"type": "mcp_call", "name": "wiki_upsert_page"}
    with pytest.raises(ValueError, match="mcp_call"):
        validate_response(response, agent_request, provenance)


def test_tool_discovery_failure_is_not_silently_ignored(agent_request, provenance):
    response = response_for(unknown_analysis())
    response["output"].insert(0, {"type": "mcp_list_tools", "error": {"message": "Unauthorized"}})
    with pytest.raises(ValueError, match="discovery failed"):
        validate_response(response, agent_request, provenance)


def test_model_cannot_supply_provenance(agent_request, provenance):
    output = unknown_analysis()
    output["provenance"] = provenance.model_dump()
    with pytest.raises(ValidationError):
        validate_response(response_for(output), agent_request, provenance)


def test_model_cannot_supply_request_id(agent_request, provenance):
    output = unknown_analysis()
    output["request_id"] = str(agent_request.request_id)
    with pytest.raises(ValidationError):
        validate_response(response_for(output), agent_request, provenance)


@pytest.mark.parametrize(
    "response",
    [
        {"status": "failed", "output": []},
        {"status": "incomplete", "output": []},
        {"status": "completed", "output": []},
        {"status": "completed", "output": [{"type": "mcp_approval_request"}]},
        {
            "status": "completed",
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "No"}]}],
        },
    ],
)
def test_incomplete_refused_or_pending_responses_fail(response, agent_request, provenance):
    with pytest.raises(ValueError):
        validate_response(response, agent_request, provenance)
