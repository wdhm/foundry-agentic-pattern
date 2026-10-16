import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.prompt import OUTPUT_INSTRUCTIONS, structured_format
from contracts.v1 import AgentResult
from tools.cli import (
    analysis_from_response,
    build_request,
    invoke,
    main,
    parser,
    review_approval,
    selected_provenance,
)


def arguments():
    return [
        "invoke",
        "--agent-kind", "prompt",
        "--project-endpoint", "https://example.services.ai.azure.com/api/projects/demo",
        "--agent-version", "3",
        "--model-version", "2026-09-22",
        "--repo", "wdhm/foundry-agentic-pattern",
        "--commit", "a" * 40,
        "--documentation-standard-ref", "data/documentation-standard.md",
        "--requested-by", "demo-reviewer",
    ]


@pytest.fixture
def agent_request():
    return build_request(parser().parse_args(arguments()))


@pytest.fixture
def definition():
    return {
        "kind": "prompt",
        "model": "deployment",
        "instructions": "Existing instructions.\n" + OUTPUT_INSTRUCTIONS,
        "text": {"format": structured_format()},
        "tools": [{
            "type": "mcp",
            "server_label": "ado",
            "allowed_tools": {"tool_names": ["wiki", "wiki_upsert_page"]},
            "require_approval": {"always": {"tool_names": ["wiki_upsert_page"]}},
        }],
    }


@pytest.fixture
def provenance(definition):
    return selected_provenance(
        "doc-agent", "3", definition, {"contract_version": "1.0.0", "policy_version": "1.0.0"}, "2026-09-22"
    )


@pytest.fixture
def analysis():
    return {
        "documentation_status": "gaps_found",
        "findings": [{
            "category": "configuration", "severity": "medium", "description": "DS-14: Retry limit missing.",
            "evidence_refs": ["code"],
        }],
        "proposed_changes": [{
            "target_page": "/integration", "target_section": "Retries", "proposed_content": "Retry limit is 3.",
            "evidence_refs": ["code"],
        }],
        "missing_information": [],
        "evidence": [{
            "id": "code", "source": "git", "uri": "https://example.com/config", "version": "a" * 40,
            "excerpt": "retry_limit = 3",
        }],
        "confidence": 0.8,
        "requires_human_review": True,
    }


def raw_response(analysis):
    return {
        "id": "resp-final",
        "status": "completed",
        "output": [
            {"type": "reasoning"},
            {"type": "mcp_list_tools", "tools": []},
            {"type": "mcp_call", "status": "completed", "name": "wiki", "error": None},
            {"type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": json.dumps(analysis)}]},
        ],
    }


def sdk_response(raw):
    return SimpleNamespace(id=raw["id"], model_dump=lambda: deepcopy(raw))


def mock_client(*responses):
    client = MagicMock()
    client.responses.create.side_effect = [sdk_response(item) for item in responses]
    return client


def approval_response():
    return {
        "id": "resp-pending",
        "status": "completed",
        "output": [{
            "type": "mcp_approval_request", "id": "approval-1", "server_label": "ado",
            "name": "wiki_upsert_page", "arguments": '{"path":"/integration","content":"proposal"}',
        }],
    }


def test_request_flags_validate_and_preserve_refs():
    request_id = "4356f9f1-af44-451d-81b6-f5f294983a49"
    correlation = "0b6f1100-30e5-4dc1-a6d0-f82054555876"
    args = parser().parse_args(arguments() + [
        "--path", "config.json", "--path", "app.py", "--wiki-page", "/integration",
        "--work-item", "42", "--adr-ref", "docs/adr/example.md", "--pr-reference", "https://example.com/pull/1",
        "--request-id", request_id, "--correlation-id", correlation,
    ])
    request = build_request(args)
    assert request.request_id == UUID(request_id)
    assert request.correlation_id == UUID(correlation)
    assert request.subject.changed_paths == ["config.json", "app.py"]
    assert request.context.wiki_page_paths == ["/integration"]
    assert request.context.work_item_ids == [42]
    assert request.context.adr_refs == ["docs/adr/example.md"]
    assert request.subject.pr_reference == "https://example.com/pull/1"
    assert request.trigger == "cli"
    assert request.contract_version == "1.0.0"


@pytest.mark.parametrize("flag,value", [("--commit", "main"), ("--work-item", "0"), ("--path", " ")])
def test_request_invalid_values(flag, value):
    with pytest.raises(ValidationError):
        build_request(parser().parse_args(arguments() + [flag, value]))


def test_parser_rejects_invalid_uuid():
    with pytest.raises(SystemExit):
        parser().parse_args(arguments() + ["--request-id", "not-uuid"])


def test_ids_generated_per_request(agent_request):
    other = build_request(parser().parse_args(arguments()))
    assert agent_request.request_id != other.request_id
    assert agent_request.correlation_id != other.correlation_id


def test_provenance_uses_selected_definition_without_mutation(definition, provenance):
    original = deepcopy(definition)
    assert provenance.prompt_version == "sha256:" + hashlib.sha256(definition["instructions"].encode()).hexdigest()
    assert provenance.agent_name == "doc-agent"
    assert provenance.agent_version == "3"
    assert provenance.model == "deployment"
    assert provenance.policy_version == "1.0.0"
    assert definition == original


@pytest.mark.parametrize("mutation", ["hosted", "schema", "policy", "approval", "ungated", "conflict", "non-mcp"])
def test_preflight_rejects_unsupported_or_unsafe_version(definition, mutation):
    if mutation == "hosted":
        definition["kind"] = "hosted"
    elif mutation == "schema":
        definition["text"] = {}
    elif mutation == "policy":
        definition["instructions"] = "Please assess."
    elif mutation == "approval":
        definition["tools"][0]["require_approval"] = "never"
    elif mutation == "ungated":
        definition["tools"][0]["require_approval"] = {"always": {"tool_names": ["wiki"]}}
    elif mutation == "conflict":
        definition["tools"][0]["require_approval"]["never"] = {"tool_names": ["wiki_upsert_page"]}
    else:
        definition["tools"].append({"type": "function"})
    with pytest.raises(ValueError):
        selected_provenance("doc-agent", "3", definition, {"contract_version": "1.0.0", "policy_version": "1"}, "exact")


@pytest.mark.parametrize("metadata", [{}, {"contract_version": "0.1.0", "policy_version": "1"},
                                     {"contract_version": "1.0.0"}])
def test_missing_or_wrong_metadata_fails(definition, metadata):
    with pytest.raises(ValueError, match="metadata"):
        selected_provenance("doc-agent", "3", definition, metadata, "exact")


def test_invoke_returns_valid_result_and_real_correlation(agent_request, provenance, analysis):
    client = mock_client(raw_response(analysis))
    report = invoke(client, agent_request, provenance)
    result = AgentResult.model_validate(report["result"])
    assert result.provenance == provenance
    assert result.request_id == agent_request.request_id
    assert result.documentation_status == "gaps_found"
    assert report["run_id"] == "resp-final"
    assert report["response_ids"] == ["resp-final"]
    assert report["correlation_id"] == str(agent_request.correlation_id)
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["extra_body"]["agent_reference"] == {
        "type": "agent_reference", "name": "doc-agent", "version": "3"
    }
    assert kwargs["metadata"]["request_id"] == str(agent_request.request_id)
    assert agent_request.model_dump_json() in kwargs["input"]
    assert "tool_choice" not in kwargs


@pytest.mark.parametrize("decision,approved", [("Approve", True), ("Reject", False)])
def test_human_decision_resumes_exact_call(
    monkeypatch, capsys, agent_request, provenance, analysis, decision, approved
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: decision)
    client = mock_client(approval_response(), raw_response(analysis))
    report = invoke(client, agent_request, provenance)
    assert report["run_id"] == "resp-pending"
    assert report["response_ids"] == ["resp-pending", "resp-final"]
    first, resumed = [call.kwargs for call in client.responses.create.call_args_list]
    assert resumed["previous_response_id"] == "resp-pending"
    assert resumed["extra_body"] == first["extra_body"]
    assert resumed["input"] == [{
        "type": "mcp_approval_response", "approval_request_id": "approval-1", "approve": approved,
    }]
    err = capsys.readouterr().err
    assert "wiki_upsert_page" in err and "/integration" in err and "proposal" in err and "ado" in err


@pytest.mark.parametrize("decision", ["", "yes", "approve", "anything"])
def test_invalid_decision_never_resumes(monkeypatch, agent_request, provenance, decision):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: decision)
    client = mock_client(approval_response())
    with pytest.raises(ValueError, match="explicit"):
        invoke(client, agent_request, provenance)
    assert client.responses.create.call_count == 1


def test_noninteractive_approval_never_resumes(monkeypatch, agent_request, provenance):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    client = mock_client(approval_response())
    with pytest.raises(ValueError, match="interactive"):
        invoke(client, agent_request, provenance)
    assert client.responses.create.call_count == 1


def test_eof_approval_never_resumes(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError))
    with pytest.raises(ValueError, match="input ended"):
        review_approval(approval_response()["output"][0])


@pytest.mark.parametrize("key", ["id", "server_label", "name", "arguments"])
def test_missing_tool_details_are_not_reviewable(key):
    item = approval_response()["output"][0]
    del item[key]
    with pytest.raises(ValueError, match=key):
        review_approval(item)


def test_multiple_approval_rounds_and_calls(monkeypatch, agent_request, provenance, analysis):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=["Reject", "Approve", "Reject"]))
    pending = approval_response()
    second = deepcopy(pending["output"][0])
    second["id"] = "approval-2"
    pending["output"].append(second)
    next_round = approval_response()
    next_round["id"] = "resp-next"
    next_round["output"][0]["id"] = "approval-3"
    client = mock_client(pending, next_round, raw_response(analysis))
    report = invoke(client, agent_request, provenance)
    assert report["response_ids"] == ["resp-pending", "resp-next", "resp-final"]
    assert len(client.responses.create.call_args_list[1].kwargs["input"]) == 2
    assert client.responses.create.call_args.kwargs["previous_response_id"] == "resp-next"


def test_repeated_approval_not_replayed(monkeypatch, agent_request, provenance):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "Reject")
    again = approval_response()
    again["id"] = "resp-again"
    client = mock_client(approval_response(), again)
    with pytest.raises(ValueError, match="repeated approval"):
        invoke(client, agent_request, provenance)
    assert client.responses.create.call_count == 2


def test_tool_error_before_approval_stops_without_resume(monkeypatch, agent_request, provenance):
    pending = approval_response()
    pending["output"].insert(0, {"type": "mcp_list_tools", "error": {"message": "Unauthorized"}})
    reviewer = MagicMock()
    monkeypatch.setattr("builtins.input", reviewer)
    client = mock_client(pending)
    with pytest.raises(ValueError, match="discovery failed"):
        invoke(client, agent_request, provenance)
    reviewer.assert_not_called()
    assert client.responses.create.call_count == 1


@pytest.mark.parametrize("response_id", ["", "resp-pending"])
def test_missing_or_repeated_response_id_stops(monkeypatch, agent_request, provenance, response_id):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "Reject")
    again = approval_response()
    again["id"] = response_id
    client = mock_client(approval_response(), again)
    with pytest.raises(ValueError, match="response ID"):
        invoke(client, agent_request, provenance)
    assert client.responses.create.call_count == 2


@pytest.mark.parametrize("status", ["failed", "cancelled", "in_progress", "queued"])
def test_failed_or_pending_run_has_no_result(agent_request, provenance, status):
    client = mock_client({"id": "resp-failed", "status": status, "output": []})
    with pytest.raises(ValueError, match="not ready"):
        invoke(client, agent_request, provenance)


@pytest.mark.parametrize("mutation", ["incomplete", "refusal", "empty", "multiple", "tool-error",
                                    "discovery-error", "unhandled", "bad-json", "bad-ref", "invented-provenance"])
def test_invalid_outputs_never_become_results(analysis, mutation):
    raw = raw_response(analysis)
    content = raw["output"][-1]["content"]
    if mutation == "incomplete":
        raw["status"] = "incomplete"
    elif mutation == "refusal":
        content[0] = {"type": "refusal", "refusal": "No"}
    elif mutation == "empty":
        raw["output"] = []
    elif mutation == "multiple":
        content.append(deepcopy(content[0]))
    elif mutation == "tool-error":
        raw["output"][2]["error"] = {"message": "Forbidden"}
    elif mutation == "discovery-error":
        raw["output"][1]["error"] = {"message": "Unauthorized"}
    elif mutation == "unhandled":
        raw["output"].append({"type": "function_call"})
    elif mutation == "bad-json":
        content[0]["text"] = "not-json"
    else:
        if mutation == "bad-ref":
            analysis["findings"][0]["evidence_refs"] = ["missing"]
        else:
            analysis["provenance"] = {"agent_version": "invented"}
        content[0]["text"] = json.dumps(analysis)
    with pytest.raises(ValueError):
        analysis_from_response(raw)


@pytest.mark.parametrize("flag,value", [("--agent-version", "latest"), ("--agent-version", "0"),
                                       ("--model-version", "unknown"), ("--commit", "bad")])
def test_main_fails_before_network(flag, value, capsys):
    assert main(arguments() + [flag, value]) == 1
    assert capsys.readouterr().out == ""


def test_main_uses_existing_version_without_configuration(monkeypatch, definition, analysis, capsys):
    project = MagicMock()
    project.__enter__.return_value = project
    project.agents.get_version.return_value = SimpleNamespace(
        name="doc-agent", version="3", definition=SimpleNamespace(as_dict=lambda: definition),
        metadata={"contract_version": "1.0.0", "policy_version": "1.0.0"},
    )
    client = mock_client(raw_response(analysis))
    project.get_openai_client.return_value.__enter__.return_value = client
    monkeypatch.setattr("azure.ai.projects.AIProjectClient", lambda **kwargs: project)
    monkeypatch.setattr("azure.identity.AzureCliCredential", MagicMock())
    assert main(arguments()) == 0
    report = json.loads(capsys.readouterr().out)
    AgentResult.model_validate(report["result"])
    project.agents.get_version.assert_called_once_with("doc-agent", "3")
    project.agents.create_version.assert_not_called()
    project.agents.update_version.assert_not_called()


def test_main_auth_failure_is_explicit(monkeypatch, capsys):
    from azure.core.exceptions import ClientAuthenticationError

    monkeypatch.setattr(
        "azure.ai.projects.AIProjectClient", MagicMock(side_effect=ClientAuthenticationError("Sign in with az login"))
    )
    monkeypatch.setattr("azure.identity.AzureCliCredential", MagicMock())
    assert main(arguments()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "az login" in captured.err
