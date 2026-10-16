import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from contracts.prompt import structured_format

ROOT = Path(__file__).parents[2]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load_module("gap_config", "src/agents/documentation-prompt/configure.py")
checker = load_module("gap_checker", "evals/check_planted_gaps.py")


def test_prompt_config_is_idempotent_and_preserves_existing_tools():
    original = {
        "kind": "prompt",
        "model": "example",
        "instructions": "Existing instructions. Use knowledge and cite DS-xx; standard is not evidence.",
        "tools": [
            {"server_label": "knowledge", "require_approval": "never"},
            {"server_label": "github", "require_approval": "never"},
            {"server_label": "ado", "require_approval": {"always": {"tool_names": ["wiki_upsert_page"]}}},
        ],
        "reasoning": {"effort": "low"},
    }
    before = deepcopy(original)
    prompt = config.PROMPT_PATH.read_text().strip()
    policy = config.POLICY_PATH.read_text().strip()
    updated = config.assessment_definition(original, prompt, policy)
    assert original == before
    for field in ("model", "tools", "reasoning"):
        assert updated[field] == before[field]
    assert updated["instructions"].startswith(before["instructions"])
    assert updated["text"]["format"] == structured_format()
    assert config.assessment_definition(updated, prompt, policy) == updated
    later = config.assessment_definition(updated, "Updated workflow", policy)
    assert later["instructions"].count(config.START) == 1
    assert prompt not in later["instructions"]
    assert "Updated workflow" in later["instructions"]


@pytest.mark.parametrize(
    "instructions",
    [
        config.START,
        config.END,
        config.END + config.START,
        config.START + config.START + config.END,
    ],
)
def test_invalid_prompt_markers_fail(instructions):
    with pytest.raises(ValueError):
        config.assessment_definition({"kind": "prompt", "instructions": instructions}, "prompt", "policy")


def unknown_result():
    return {
        "documentation_status": "insufficient_information",
        "findings": [],
        "proposed_changes": [],
        "missing_information": [{"description": "Owner unavailable", "expected_source": "work item"}],
        "evidence": [],
        "confidence": 0,
        "requires_human_review": True,
    }


def message(result):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(result)}]}


def test_checker_parses_completed_analysis_after_reads():
    raw = {
        "status": "completed",
        "output": [
            {"type": "mcp_list_tools"},
            {"type": "mcp_call", "status": "completed", "server_label": "knowledge"},
            message(unknown_result()),
        ],
    }
    assert checker.response_analysis(raw) == unknown_result()


@pytest.mark.parametrize(
    "item",
    [
        {"type": "mcp_approval_request"},
        {"type": "mcp_call", "status": "failed"},
        {"type": "mcp_list_tools", "error": {"message": "Forbidden"}},
        {"type": "message", "role": "assistant", "content": [{"type": "refusal"}]},
    ],
)
def test_checker_rejects_errors_refusals_and_pending_approvals(item):
    with pytest.raises(ValueError):
        checker.response_analysis({"status": "completed", "output": [item, message(unknown_result())]})


def test_checker_rejects_incomplete_response():
    with pytest.raises(ValueError, match="did not complete"):
        checker.response_analysis({"status": "incomplete", "output": [message(unknown_result())]})


def test_checker_validates_semantics_not_just_json():
    result = unknown_result()
    result["documentation_status"] = "up_to_date"
    with pytest.raises(ValueError):
        checker.response_analysis({"status": "completed", "output": [message(result)]})


def read_call(server, name, arguments, output):
    return {
        "type": "mcp_call",
        "server_label": server,
        "name": name,
        "status": "completed",
        "arguments": json.dumps(arguments),
        "output": json.dumps(output),
    }


@pytest.fixture
def source_trace():
    sha = "a" * 40
    git_uri = f"https://github.com/example/repo/blob/{sha}/config.json"
    wiki_uri = "https://dev.azure.com/example/project/_wiki/wikis/wiki?pagePath=%2FOverview"
    item_uri = "https://dev.azure.com/example/project/_apis/wit/workItems/1"
    calls = [
        read_call("knowledge", "knowledge_base_retrieve", {}, {"documents": []}),
        read_call(
            "github",
            "get_file_contents",
            {"owner": "example", "repo": "repo", "path": "config.json", "sha": sha},
            {"documents": [{"content": '{\n  "maxAttempts": 5\n}'}]},
        ),
        read_call(
            "ado",
            "wiki",
            {"action": "get_page"},
            {
                "page": {"remoteUrl": wiki_uri, "url": wiki_uri, "content": "Order Sync overview."},
                "eTag": ['"abc123"'],
            },
        ),
        read_call(
            "ado",
            "wit_work_item",
            {"action": "get", "id": 1},
            {
                "id": 1,
                "rev": 2,
                "url": item_uri,
                "fields": {"System.Title": "Maintain Order Sync", "System.Description": "A &amp; B"},
            },
        ),
    ]
    result = {
        "evidence": [
            {"id": "G1", "source": "git", "uri": git_uri, "version": sha, "excerpt": '"maxAttempts": 5'},
            {"id": "W1", "source": "wiki", "uri": wiki_uri, "version": '"abc123"', "excerpt": "Order Sync overview."},
            {
                "id": "I1",
                "source": "work_item",
                "uri": item_uri.replace("/_apis/wit/workItems/", "/_workitems/edit/"),
                "version": "2",
                "excerpt": "A & B",
            },
        ]
    }
    return {"status": "completed", "output": calls}, result


def test_trace_matches_source_uri_version_and_actual_excerpt(source_trace):
    raw, result = source_trace
    assert checker.trace_evidence_problems(raw, result) == []


@pytest.mark.parametrize(
    "index,field,value",
    [
        (0, "uri", "https://github.com/example/another-repo/blob/" + "a" * 40 + "/config.json"),
        (0, "version", "b" * 40),
        (0, "excerpt", '"maxAttempts": 999'),
        (1, "version", '"changed-page"'),
        (1, "excerpt", "This page does not document retry settings."),
        (2, "version", "999"),
        (2, "uri", "https://dev.azure.com/example/project/_workitems/edit/999"),
    ],
)
def test_trace_rejects_fabricated_evidence(source_trace, index, field, value):
    raw, result = source_trace
    result["evidence"][index][field] = value
    assert checker.trace_evidence_problems(raw, result)


def test_trace_does_not_accept_pr_description_instead_of_file_content(source_trace):
    raw, result = source_trace
    raw["output"][1]["name"] = "pull_request_read"
    assert checker.trace_evidence_problems(raw, result)


def test_trace_requires_standard_retrieval(source_trace):
    raw, result = source_trace
    raw["output"] = raw["output"][1:]
    assert "standard" in checker.trace_evidence_problems(raw, result)[0]


def test_trace_rejects_write_calls(source_trace):
    raw, result = source_trace
    raw["output"].append(read_call("ado", "wiki_upsert_page", {}, {}))
    assert any("write" in problem for problem in checker.trace_evidence_problems(raw, result))


def test_trace_ignores_directory_listing_as_evidence(source_trace):
    raw, result = source_trace
    raw["output"][1]["output"] = '[]\n{"structuredResponse":[]}'
    assert checker.trace_evidence_problems(raw, result)


def test_configuration_preserves_instructions_added_after_managed_block():
    base = config.assessment_definition({"kind": "prompt", "instructions": "Original"}, "Prompt", "Policy")
    base["instructions"] += "\nLater P2 instructions."
    updated = config.assessment_definition(base, "Revised prompt", "Policy")
    assert updated["instructions"].endswith("\nLater P2 instructions.")
    assert "Revised prompt" in updated["instructions"]
