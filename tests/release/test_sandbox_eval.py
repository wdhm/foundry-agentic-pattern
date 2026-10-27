"""Synthetic transport tests; these do not claim Azure DevOps or model execution."""

import asyncio
import base64
import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from tools.eval_loop import LiveDemo, LoopConfig
from tools.release_sources import blob_id
from tools.sandbox_eval import (
    ADO_AUDIENCE,
    MAX_RESPONSE_BYTES,
    AzureDevOpsReader,
    Capture,
    NoRedirect,
    SandboxPlan,
    capture_sources,
    check_identity,
    evaluate_capture,
    main,
    prepared_case,
    validate_capture,
)


@pytest.fixture
def plan():
    return SandboxPlan(
        organization="foundry-agentic", project="integration-team", repository="integration-team",
        commit="a" * 40, paths=["/src/order_sync.py", "/config/settings.json"],
        wiki="integration-team.wiki", wiki_path="/Order Sync/Overview",
        wiki_commit="b" * 40, wiki_etag=blob_id("Sparse documentation.\n"),
        read_identity={"tenant_id": uuid4(), "object_id": uuid4(), "client_id": uuid4()},
        read_approval_reference="TEST ONLY approved reads",
        question="What retry policy is implemented and is it documented?", scope="change_review",
        expected_status="gaps_found", expectation_review_reference="TEST ONLY reviewed expected status",
    )


def token(plan, **updates):
    claims = {
        "aud": ADO_AUDIENCE, "oid": str(plan.read_identity.object_id),
        "tid": str(plan.read_identity.tenant_id), "appid": str(plan.read_identity.client_id), **updates,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "header." + encoded + ".signature"


def transport(plan):
    calls = []

    def get(uri):
        calls.append(uri)
        if "/_apis/git/" in uri:
            path = plan.paths[len(calls) - 1]
            text = "maxAttempts = 5\n"
            return {"path": path, "commitId": plan.commit, "objectId": blob_id(text), "content": text}, {}
        return {"path": plan.wiki_path, "content": "Sparse documentation.\n"}, {"etag": '"' + plan.wiki_etag + '"'}

    return get, calls


def config(plan):
    return LoopConfig(
        mode="supplied_sources_only",
        settings={
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://isolated.services.ai.azure.com/api/projects/evaluation",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "candidate", "DOCUMENTATION_MODEL_VERSION": "2026-03-05",
            "DOCUMENTATION_ADO_PROJECT": plan.project, "DOCUMENTATION_ADO_WIKI": plan.wiki,
            "DOCUMENTATION_AUTH_MODE": "azure_cli",
        },
        observed_model="gpt-5.4-2026-03-05", evaluator_deployment="judge", evaluator_version="2026-03-17",
        optimizer_deployment="optimizer", optimizer_version="2026-03-17",
        isolation_review_reference="TEST ONLY isolated config",
        serving_project_endpoint="https://serving.services.ai.azure.com/api/projects/production",
    )


def test_capture_exact_pins_contract_and_no_gold_input(plan):
    get, calls = transport(plan)
    capture = capture_sources(plan, get)
    validate_capture(plan, capture)
    assert len(calls) == len(plan.paths) + 1
    assert all("versionDescriptor.version=" in uri and "includeContent=true" in uri for uri in calls)
    assert capture.payload.source_mode == "supplied_sources"
    assert capture.payload.request.subject.repo.endswith("/_git/integration-team")
    assert all(source.sha256 for source in capture.payload.sources)
    assert plan.expected_status not in capture.payload.model_dump_json()
    assert plan.expectation_review_reference not in capture.payload.model_dump_json()
    case = prepared_case(plan, capture)
    assert case["scope"] == plan.scope and case["expected_status"] == plan.expected_status
    assert case["request"].request_id != capture.payload.request.request_id


@pytest.mark.parametrize("field,value", [
    ("paths", ["/../secret"]), ("paths", ["/src/a", "/src/a"]), ("paths", ["/src/%2e%2e/secret"]),
    ("paths", ["/src\\secret"]), ("paths", ["/src/a?x=1"]), ("wiki_path", "/../page"),
    ("organization", "other/org"), ("commit", "main"), ("paths", ["/a"] * 6),
])
def test_reject_ambiguous_or_unbounded_plans(plan, field, value):
    with pytest.raises(ValueError):
        SandboxPlan.model_validate({**plan.model_dump(), field: value})


@pytest.mark.parametrize("claims", [
    {"oid": str(uuid4())}, {"tid": str(uuid4())}, {"appid": str(uuid4())},
    {"aud": "https://management.azure.com/"}, {"scp": "user_impersonation"},
])
def test_wrong_or_delegated_identity_rejected_before_io(plan, claims):
    with pytest.raises(ValueError, match="approved application identity"):
        AzureDevOpsReader(plan, token(plan, **claims))


def test_malformed_identity_rejected(plan):
    with pytest.raises(ValueError, match="Cannot establish"):
        check_identity("not-a-token", plan.read_identity)
    check_identity(token(plan), plan.read_identity)


@pytest.mark.parametrize("field,value", [
    ("commitId", "c" * 40), ("objectId", "c" * 40), ("path", "/other.py"), ("content", None),
])
def test_repository_drift_stops_capture(plan, field, value):
    get, calls = transport(plan)

    def drift(uri):
        item, headers = get(uri)
        item[field] = value
        return item, headers

    with pytest.raises(ValueError, match="Repository response"):
        capture_sources(plan, drift)
    assert len(calls) == 1


@pytest.mark.parametrize("bad_etag,bad_content", [(True, False), (False, True)])
def test_wiki_drift_stops_capture(plan, bad_etag, bad_content):
    get, _ = transport(plan)

    def drift(uri):
        item, headers = get(uri)
        if "/_apis/wiki/" in uri:
            if bad_etag:
                headers["etag"] = "c" * 40
            if bad_content:
                item["content"] = "changed"
        return item, headers

    with pytest.raises(ValueError, match="Wiki response"):
        capture_sources(plan, drift)


def test_source_budget_exact_boundary(plan):
    plan = plan.model_copy(update={"paths": ["/src/order_sync.py"]})

    def get(uri):
        if "/_apis/git/" in uri:
            content = "x" * (80_000 - len("Sparse documentation.\n"))
            return {
                "path": plan.paths[0], "commitId": plan.commit, "objectId": blob_id(content), "content": content,
            }, {}
        return {"path": plan.wiki_path, "content": "Sparse documentation.\n"}, {"etag": plan.wiki_etag}

    validate_capture(plan, capture_sources(plan, get))

    def oversized(uri):
        item, headers = get(uri)
        if "/_apis/git/" in uri:
            item["content"] += "x"
            item["objectId"] = blob_id(item["content"])
        return item, headers

    with pytest.raises(ValueError, match="input budget"):
        capture_sources(plan, oversized)


def test_reader_does_not_redirect_or_read_outside_allowlist(plan):
    reader = AzureDevOpsReader(plan, token(plan))
    with pytest.raises(ValueError, match="boundary"):
        reader.get("https://example.com/secret")
    assert reader.remaining == 3
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com") is None


def test_reader_http_failure_redacts_body_and_url(plan):
    reader = AzureDevOpsReader(plan, token(plan))
    reader.opener = SimpleNamespace(open=lambda *args, **kwargs: (_ for _ in ()).throw(
        HTTPError("https://secret.example", 401, "PRIVATE TEXT", {}, BytesIO(b"PRIVATE BODY")),
    ))
    with pytest.raises(ValueError, match="HTTP 401") as error:
        reader.get(next(iter(reader.allowed)))
    assert "PRIVATE" not in str(error.value) and "secret.example" not in str(error.value)


def test_reader_limits_response_and_request_budget(plan):
    reader = AzureDevOpsReader(plan, token(plan))
    response = BytesIO(b"x" * (MAX_RESPONSE_BYTES + 1))
    reader.opener = SimpleNamespace(open=lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="response exceeds"):
        reader.get(next(iter(reader.allowed)))
    reader.remaining = 0
    with pytest.raises(ValueError, match="request budget"):
        reader.get(next(iter(reader.allowed)))


def test_replay_rejects_modified_plan_capture_and_standard(plan):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    with pytest.raises(ValueError, match="reviewed source plan"):
        validate_capture(plan.model_copy(update={"commit": "d" * 40}), capture)
    raw = json.loads(capture.model_dump_json())
    raw["payload"]["sources"][0]["content"] = "tampered"
    with pytest.raises(ValueError):
        Capture.model_validate(raw)
    changed = deepcopy(capture)
    changed.payload.standard = None
    with pytest.raises(ValueError, match="standard"):
        validate_capture(plan, changed)


@pytest.mark.parametrize("passed", [True, False])
def test_reuses_existing_runner_once_no_optimizer_or_live_tool_claim(plan, tmp_path, monkeypatch, passed):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    invocations = []

    async def evaluate(demo, candidate, output):
        assert candidate == "" and demo.cases[0]["id"] == "sandbox-assessment"
        assert demo.cases[0]["mode"] == "supplied_sources"
        invocations.append(demo)
        return passed, 1.0, {}

    monkeypatch.setattr(LiveDemo, "evaluate", evaluate)
    output = tmp_path / "run"
    result = asyncio.run(evaluate_capture(plan, capture, config(plan), object(), output))
    assert len(invocations) == 1
    assert result["status"] == ("sandbox_passed" if passed else "sandbox_failed")
    assert result["full_suite_passed"] is False and result["promoted"] is False
    assert result["coverage"]["tool_call_accuracy"] == "not_evaluated"
    assert result["coverage"]["agent_driven_source_retrieval"] is False
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["limits"]["optimizer_calls"] == 0
    with pytest.raises(FileExistsError):
        asyncio.run(evaluate_capture(plan, capture, config(plan), object(), output))


def test_serving_target_is_rejected_without_model_calls(plan, tmp_path):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    settings = config(plan)
    settings.serving_project_endpoint = settings.settings["DOCUMENTATION_PROJECT_ENDPOINT"]
    with pytest.raises(ValueError):
        asyncio.run(evaluate_capture(plan, capture, settings, object(), tmp_path / "run"))
    assert not (tmp_path / "run").exists()


def test_operational_failure_keeps_blocked_redacted_decision(plan, tmp_path, monkeypatch):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)

    async def fail(*args):
        raise RuntimeError("PRIVATE SOURCE AND MODEL BODY")

    monkeypatch.setattr(LiveDemo, "evaluate", fail)
    output = tmp_path / "run"
    with pytest.raises(RuntimeError):
        asyncio.run(evaluate_capture(plan, capture, config(plan), object(), output))
    decision = json.loads((output / "decision.json").read_text())
    assert decision["status"] == "blocked" and decision["full_suite_passed"] is False
    assert decision["error"] == {"exception": "RuntimeError"}
    assert "PRIVATE" not in (output / "decision.json").read_text()


@pytest.mark.parametrize("change", ["mode", "domain"])
def test_wrong_evaluation_configuration_is_rejected_before_cloud(plan, tmp_path, change):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    settings = config(plan)
    if change == "mode":
        settings.mode = "full_suite"
    else:
        settings.settings["DOCUMENTATION_ADO_PROJECT"] = "other-project"
    with pytest.raises(ValueError):
        asyncio.run(evaluate_capture(plan, capture, settings, object(), tmp_path / "run"))
    assert not (tmp_path / "run").exists()


def test_cli_read_approval_is_required_before_credentials(plan, tmp_path, capsys):
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json())
    output = tmp_path / "capture.json"
    assert main(["capture", "--plan", str(path), "--output", str(output)]) == 1
    assert "approval is required" in capsys.readouterr().err
    assert not output.exists()
