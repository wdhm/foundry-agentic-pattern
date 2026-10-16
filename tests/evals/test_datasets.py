"""Offline dataset integrity checks, not model evaluations or baseline results."""

import ast
import hashlib
import json
import re
import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from contracts.v1 import AgentRequest, AnalysisOutput

ROOT = Path(__file__).parents[2]
DATASETS = ROOT / "evals" / "datasets"
SUITE = json.loads((DATASETS / "suite.json").read_text(encoding="utf-8"))
SOURCES = {source["id"]: source for source in SUITE["sources"]}
CHECK = runpy.run_path(str(ROOT / "evals" / "check_planted_gaps.py"))["check"]
CASES = SUITE["cases"]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def git_blob(text):
    content = text.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()


def scenario_for(case):
    return read_json(DATASETS / case["scenario_file"])


def synthetic_analysis(case):
    """Mechanical unit-test payload; never persisted or represented as an agent run."""
    scenario = scenario_for(case)
    evidence = []
    for source_id in case["source_ids"]:
        source = SOURCES[source_id]
        evidence.append(
            {
                "id": source_id,
                "source": source["source"],
                "uri": source["uri"],
                "version": source["version"],
                "excerpt": "Synthetic checker unit-test excerpt; not an observed agent response.",
            }
        )
    return {
        "documentation_status": scenario["expected_status"],
        "findings": [
            {
                "category": "unit-test",
                "severity": "medium",
                "description": gap["title"],
                "evidence_refs": [evidence[0]["id"]],
            }
            for gap in scenario.get("planted_gaps", [])
        ],
        "proposed_changes": [],
        "missing_information": [
            {"description": item["title"], "expected_source": "Unit-test source"}
            for item in scenario.get("expected_missing", [])
        ],
        "evidence": evidence,
        "confidence": 0,
        "requires_human_review": True,
    }


def test_suite_interface_and_case_inventory():
    assert set(SUITE) == {"dataset_version", "contract_version", "documentation_standard", "sources", "cases"}
    assert SUITE["dataset_version"] == SUITE["contract_version"] == "1.0.0"
    assert len(CASES) == len({case["id"] for case in CASES}) == 5
    assert len(SOURCES) == len(SUITE["sources"])
    assert {case["scenario_file"] for case in CASES} == {path.name for path in DATASETS.glob("order-sync-*.json")}
    assert len({case["request"]["request_id"] for case in CASES}) == 5
    assert len({case["request"]["correlation_id"] for case in CASES}) == 5


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_case_contract_and_ground_truth(case):
    assert set(case) == {
        "id",
        "scenario_file",
        "input_mode",
        "source_ids",
        "request",
        "rationale",
        "reference_answer",
        "forbidden_claims",
        "integration_blockers",
        "baseline",
    }
    request = AgentRequest.model_validate(case["request"])
    schema = read_json(ROOT / "src" / "contracts" / "schema" / "v1" / "AgentRequest.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(case["request"])
    scenario = scenario_for(case)
    assert scenario["scenario"] == case["id"]
    assert scenario["prompt"].strip() and case["rationale"].strip() and case["reference_answer"].strip()
    assert case["forbidden_claims"]
    assert set(scenario["expected_evidence"]["git_versions"]) == {request.subject.commit_sha}
    assert case["input_mode"] in {"live_sources", "supplied_sources"}
    assert len(set(case["source_ids"])) == len(case["source_ids"])
    sources = [SOURCES[source_id] for source_id in case["source_ids"]]
    assert all(source["version"] == request.subject.commit_sha for source in sources if source["source"] == "git")
    assert set(scenario["expected_evidence"]["required_sources"]) == {source["source"] for source in sources}
    if case["input_mode"] == "supplied_sources":
        assert all(source["source"] == "git" for source in sources)
    if "subject" in scenario:
        assert scenario["subject"]["commit_sha"] == request.subject.commit_sha
        assert scenario["context"] == case["request"]["context"]
        paths = scenario["subject"].get("changed_paths", scenario["subject"].get("paths"))
        assert paths == request.subject.changed_paths
    expected = scenario.get("planted_gaps", []) + scenario.get("expected_missing", [])
    assert expected
    assert len({item["id"] for item in expected}) == len(expected)
    standard = (ROOT / SUITE["documentation_standard"]["path"]).read_text(encoding="utf-8")
    for item in expected:
        assert item["match_all"] and all(
            group and all(term == term.lower() for term in group) for group in item["match_all"]
        )
        assert item["rules"] and all(rule in standard for rule in item["rules"])
    baseline = case["baseline"]
    assert set(baseline) == {"state", "reference", "observations"}
    assert baseline["state"] in {"historical_report_only", "not_run"}
    if baseline["state"] == "historical_report_only":
        assert (ROOT / baseline["reference"]).is_file()
    else:
        assert baseline["reference"] is None


@pytest.mark.parametrize("source", SUITE["sources"], ids=lambda source: source["id"])
def test_source_snapshot_identity(source):
    assert set(source) == {
        "id",
        "source",
        "uri",
        "version",
        "snapshot",
        "git_blob_sha",
        "availability",
        "note",
    }
    assert source["availability"] == "snapshot"
    path = (DATASETS / source["snapshot"]).resolve()
    assert path.is_relative_to(DATASETS.resolve()) and path.is_file()
    assert source["uri"].startswith("https://")
    if source["source"] == "git":
        assert re.fullmatch("[0-9a-f]{40}", source["version"])
        assert f"/blob/{source['version']}/" in source["uri"]
        assert git_blob(path.read_text(encoding="utf-8")) == source["git_blob_sha"]
    elif source["source"] == "wiki":
        snapshot = read_json(path)
        assert source["version"] == snapshot["etag"] == source["git_blob_sha"]
        assert git_blob(snapshot["content"]) == source["git_blob_sha"]
        assert snapshot["path"] == "/Order Sync/Overview"
    else:
        assert source["source"] == "work_item"
        snapshot = read_json(path)
        assert snapshot["id"] == 1 and source["version"] == str(snapshot["rev"]) == "2"
        assert source["git_blob_sha"] is None
        assert set(snapshot["fields"]) <= set(snapshot["retrieved_field_names"])
        assert set(snapshot["fields"]) == {
            "System.Title",
            "System.Description",
            "System.WorkItemType",
            "System.State",
        }
        assert snapshot["scope"]


def test_standard_is_pinned_rules_not_integration_evidence():
    standard = SUITE["documentation_standard"]
    assert standard["role"] == "rules_only"
    assert git_blob((ROOT / standard["path"]).read_text(encoding="utf-8")) == standard["git_blob_sha"]
    assert re.fullmatch("[0-9a-f]{40}", standard["commit_sha"])
    for case in CASES:
        ref = case["request"]["documentation_standard_ref"]
        assert ref.endswith(f"/blob/{standard['commit_sha']}/{standard['path']}")
        assert all(SOURCES[source_id]["uri"] != ref for source_id in case["source_ids"])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_existing_checker_accepts_case_shape_and_detects_missing_expectations(case):
    scenario = scenario_for(case)
    analysis = synthetic_analysis(case)
    AnalysisOutput.model_validate(analysis)
    report = CHECK(scenario, analysis)
    assert report["status_ok"] and report["recall"] == 1
    assert not report["evidence_problems"] and not report["missing_sources"] and not report["fabrication"]
    analysis["findings"] = []
    analysis["missing_information"] = []
    assert CHECK(scenario, analysis)["recall"] == 0


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_wrong_git_version_is_not_accepted_as_grounded(case):
    analysis = synthetic_analysis(case)
    next(item for item in analysis["evidence"] if item["source"] == "git")["version"] = "a" * 40
    assert CHECK(scenario_for(case), analysis)["evidence_problems"]


def test_status_precedence_baseline_is_not_silently_weakened():
    case = next(case for case in CASES if case["id"] == "order-sync-information-missing")
    analysis = synthetic_analysis(case)
    analysis["documentation_status"] = "gaps_found"
    analysis["findings"] = [
        {"category": "unit-test", "severity": "medium", "description": "A gap", "evidence_refs": ["base-settings"]}
    ]
    AnalysisOutput.model_validate(analysis)
    report = CHECK(scenario_for(case), analysis)
    assert report["recall"] == 1 and not report["status_ok"]
    assert "2 of 3" in case["baseline"]["observations"]


def test_contract_rejects_rule_version_as_git_and_dangling_evidence():
    analysis = synthetic_analysis(CASES[0])
    invalid = deepcopy(analysis)
    invalid["evidence"][0]["version"] = "1.0"
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(invalid)
    invalid = deepcopy(analysis)
    invalid["findings"][0]["evidence_refs"] = ["not-retrieved"]
    with pytest.raises(ValidationError, match="resolve"):
        AnalysisOutput.model_validate(invalid)


def test_fixture_facts_support_distinct_reference_answers():
    base = read_json(DATASETS / SOURCES["base-settings"]["snapshot"])
    head = read_json(DATASETS / SOURCES["pr62-settings"]["snapshot"])
    assert base["retry"] == {"maxAttempts": 3, "delaySeconds": 5}
    assert "timeoutSeconds" not in base["erp"] and "deadLetterQueue" not in base["source"]
    assert head["retry"] == {"maxAttempts": 5, "initialDelaySeconds": 2, "backoff": "exponential"}
    assert head["erp"]["timeoutSeconds"] == 30
    assert head["source"]["deadLetterQueue"] == "orders-confirmed-failed"
    code = (DATASETS / SOURCES["pr62-code"]["snapshot"]).read_text(encoding="utf-8")
    function = next(
        node for node in ast.parse(code).body if isinstance(node, ast.FunctionDef) and node.name == "dead_letter"
    )
    assert len(function.body) == 2
    assert isinstance(function.body[1], ast.Expr)
    call = function.body[1].value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print"
    wiki = read_json(DATASETS / SOURCES["order-sync-wiki"]["snapshot"])["content"].lower()
    assert not any(term in wiki for term in ("retry", "timeout", "dead-letter", "classification", "runbook"))
    assert "**Owner:** P2" in (DATASETS / SOURCES["base-readme"]["snapshot"]).read_text(encoding="utf-8")
