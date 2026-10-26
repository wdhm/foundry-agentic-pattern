import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tools.eval_loop import THRESHOLDS, LiveDemo, LoopConfig, http_failure, loop, main, quality


def test_http_failure_only_exposes_safe_metadata_through_sdk_wrapper():
    error = RuntimeError("secret response text")
    error.status_code = 403
    error.response = SimpleNamespace(
        request=SimpleNamespace(url=(
            "https://isolated.services.ai.azure.com/api/projects/evaluation-ci/openai/v1/responses?secret=token"
        )),
        headers={"x-ms-request-id": "request-123", "Authorization": "secret", "x-request-id": "invalid\nsecret"},
    )
    error.body = {
        "error": {"code": "PermissionDenied",
                  "message": "principal secret lacks Microsoft.CognitiveServices/accounts/AIServices/responses/write"},
        "request_body": "private sources",
    }
    wrapper = RuntimeError("SDK failure", error)
    assert http_failure(wrapper) == {
        "status": 403, "api_path": "/api/projects/evaluation-ci/openai/v1/responses",
        "x-ms-request-id": "request-123", "code": "PermissionDenied",
        "referenced_operations": ["Microsoft.CognitiveServices/accounts/AIServices/responses/write"],
    }
    wrapper.__cause__ = wrapper
    assert http_failure(wrapper)["status"] == 403


def test_http_failure_without_http_response_is_empty():
    assert http_failure(RuntimeError("local failure")) == {}


def rows(score=3, passed=True):
    return [{
        "datasource_item_id": 0, "status": "completed",
        "results": [
            {"name": name, "type": "azure_ai_evaluator", "score": 1 if name == "task_adherence" else score,
             "passed": passed}
            for name in THRESHOLDS
        ],
    }]


def test_thresholds_and_bad_quality_are_not_infrastructure_errors():
    assert quality(rows(), 1, THRESHOLDS) == (True, 0.6)
    assert quality(rows(2, False), 1, THRESHOLDS) == (False, 0.4)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "nan", "error", "boolean", "label"])
def test_malformed_judges_fail_early(mutation):
    value = rows()
    if mutation == "missing":
        value[0]["results"].pop()
    elif mutation == "duplicate":
        value.append(value[0])
    elif mutation == "nan":
        value[0]["results"][0]["score"] = float("nan")
    elif mutation == "error":
        value[0]["error"] = "auth"
    elif mutation == "boolean":
        value[0]["results"][0]["score"] = True
    else:
        value[0]["results"][0]["label"] = "fail"
    with pytest.raises(ValueError):
        quality(value, 1, THRESHOLDS)


@pytest.mark.parametrize("pass_at,expected,calls", [(1, "passed", 1), (3, "passed", 3), (9, "exhausted", 5)])
@pytest.mark.parametrize("mode", ["full_suite", "supplied_sources_only"])
def test_five_total_candidates_and_real_revisions(tmp_path, pass_at, expected, calls, mode):
    evaluated, optimized = [], []

    async def evaluate(candidate, output):
        evaluated.append(candidate)
        return len(evaluated) >= pass_at, len(evaluated) / 5, {"failure": "groundedness"}

    async def improve(candidate, feedback):
        optimized.append(feedback)
        return candidate + "Better instructions.\n"

    output = tmp_path / "run"
    result = asyncio.run(loop(evaluate, improve, output, {"coverage": {"mode": mode}}))
    assert result["status"] == (
        "partial_passed" if expected == "passed" and mode == "supplied_sources_only" else expected
    )
    assert len(evaluated) == calls
    assert len(set(evaluated)) == calls
    assert len(optimized) == calls - 1
    assert result["best_attempt"] == calls
    assert result["promotion_eligible"] is False
    assert json.loads((output / "decision.json").read_text()) == result
    assert (output / "best-instructions.txt").read_text() == evaluated[-1]
    assert result["full_suite_passed"] == (expected == "passed" and mode == "full_suite")


@pytest.mark.parametrize("revised", ["", "   ", "x" * 12001])
def test_invalid_improvement_stops(tmp_path, revised):
    async def evaluate(candidate, output):
        return False, 0.1, {}

    async def improve(candidate, feedback):
        return revised

    assert asyncio.run(loop(evaluate, improve, tmp_path / "run"))["status"] == "no_safe_improvement"


def test_cycle_stops_instead_of_rerunning(tmp_path):
    async def evaluate(candidate, output):
        return False, 0.1, {}

    async def improve(candidate, feedback):
        return "unchanged"

    result = asyncio.run(loop(evaluate, improve, tmp_path / "run"))
    assert result["status"] == "no_safe_improvement"
    assert len(result["attempts"]) == 2


def test_passing_candidate_replaces_higher_ranked_failure(tmp_path):
    async def evaluate(candidate, output):
        return (True, 0.6, {}) if candidate else (False, 0.9, {})

    async def improve(candidate, feedback):
        return "Passing guidance."

    output = tmp_path / "run"
    result = asyncio.run(loop(evaluate, improve, output))
    assert result["status"] == "passed"
    assert result["best_attempt"] == 2
    assert (output / "best-instructions.txt").read_text() == "Passing guidance."
    assert json.loads((output / "decision.json").read_text())["best_attempt"] == 2


def test_operational_error_never_calls_optimizer(tmp_path):
    async def evaluate(candidate, output):
        raise ValueError("auth or schema failure")

    async def improve(candidate, feedback):
        pytest.fail("must not optimize operational errors")

    output = tmp_path / "run"
    with pytest.raises(ValueError, match="auth or schema"):
        asyncio.run(loop(evaluate, improve, output))
    assert json.loads((output / "decision.json").read_text())["status"] == "blocked"
    assert (output / "summary.md").is_file()


def test_no_approval_never_reads_config_or_calls_cloud(tmp_path):
    assert main(["--config", str(tmp_path / "absent"), "--output", str(tmp_path / "run")]) == 1
    assert json.loads((tmp_path / "run" / "decision.json").read_text())["status"] == "blocked"


def test_existing_evidence_is_never_reused_as_a_new_success(tmp_path, monkeypatch):
    output = tmp_path / "old"
    output.mkdir()
    (output / "summary.md").write_text("old passing summary")
    summary = tmp_path / "actions.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main(["--config", str(tmp_path / "absent"), "--output", str(output)]) == 1
    assert not summary.exists()


def test_serving_project_rejected_before_source_or_network(tmp_path):
    endpoint = "https://example.services.ai.azure.com/api/projects/serving"
    config = LoopConfig(
        observed_model="agent",
        settings={
            "DOCUMENTATION_PROJECT_ENDPOINT": endpoint,
            "TOOLBOX_ENDPOINT": endpoint + "/toolboxes/read/mcp?api-version=v1",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "agent", "DOCUMENTATION_MODEL_VERSION": "1",
            "DOCUMENTATION_ADO_PROJECT": "demo", "DOCUMENTATION_ADO_WIKI": "demo",
            "DOCUMENTATION_AUTH_MODE": "azure_cli",
        },
        evaluator_deployment="judge", evaluator_version="1",
        optimizer_deployment="optimizer", optimizer_version="1",
        isolation_review_reference="review", serving_project_endpoint=endpoint,
    )
    with pytest.raises(ValueError, match="separate isolated"):
        LiveDemo(config, None)


@pytest.mark.parametrize("failure", [None, "budget", "replay", "wrong-status", "schema", "source", "auth"])
@pytest.mark.parametrize("mode", ["full_suite", "supplied_sources_only"])
def test_actual_agent_sdk_path_uses_new_guidance_and_bounded_fresh_calls(monkeypatch, tmp_path, failure, mode):
    """Offline transport double; this test does not assert semantic agent quality."""
    from agent_framework import (
        BaseChatClient,
        ChatMiddlewareLayer,
        ChatResponse,
        Content,
        FunctionInvocationLayer,
        Message,
    )

    from tools.hosted_evaluation import evaluator_row

    settings = {
        "DOCUMENTATION_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/isolated",
        "TOOLBOX_ENDPOINT": "https://example.services.ai.azure.com/api/projects/isolated/toolboxes/read/mcp?api-version=v1",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "agent", "DOCUMENTATION_MODEL_VERSION": "1",
        "DOCUMENTATION_ADO_PROJECT": "demo", "DOCUMENTATION_ADO_WIKI": "demo",
        "DOCUMENTATION_AUTH_MODE": "azure_cli",
    }
    if mode == "supplied_sources_only":
        del settings["TOOLBOX_ENDPOINT"]
    config = LoopConfig(
        mode=mode,
        observed_model="agent",
        settings=settings, evaluator_deployment="judge", evaluator_version="1",
        optimizer_deployment="optimizer", optimizer_version="1",
        isolation_review_reference="review",
        serving_project_endpoint="https://example.services.ai.azure.com/api/projects/serving",
    )
    observed, reports = [], []

    class Resource:
        def __init__(self, *args, **kwargs):
            self.functions = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Transport(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
        def __init__(self, *, middleware, function_invocation_configuration, **kwargs):
            super().__init__(
                middleware=middleware, function_invocation_configuration=function_invocation_configuration,
            )
            self.client = Resource()

        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            assert options["max_tokens"] == 4096
            assert options["store"] is False
            observed.append(str(messages))
            answer = {
                "documentation_status": "insufficient_information",
                "findings": [], "proposed_changes": [],
                "missing_information": [{"description": "Unknown.", "expected_source": "wiki"}],
                "evidence": [], "confidence": 0.5, "requires_human_review": True,
            }
            payload = json.loads(next(message.text for message in messages if message.role == "user"))
            if failure in {"wrong-status", "source"} and payload.get("source_mode") == "supplied_sources":
                source = payload["sources"][0]
                answer.update(
                    documentation_status="up_to_date", missing_information=[],
                    evidence=[{
                        "id": "source", "source": source["source"], "uri": source["uri"],
                        "version": source["version"],
                        "excerpt": "not in source" if failure == "source" else source["content"][:100],
                    }],
                )
            return ChatResponse(
                messages=[Message("assistant", [Content.from_text(
                    "invalid JSON" if failure == "schema" else json.dumps(answer),
                )])],
                response_id="same" if failure == "replay" else str(uuid4()), model="agent", finish_reason="stop",
            )

    def row(case, payload, report, definition):
        assert definition["environment_variables"] == settings
        if failure != "wrong-status":
            assert "Do not infer facts." in report.execution.instructions
        assert report.execution.model_calls[0]["status"] == "completed"
        reports.append(report)
        if (mode == "supplied_sources_only" or failure in {"wrong-status", "source"}) and (
            case["mode"] == "supplied_sources"
        ):
            return evaluator_row(case, payload, report, definition)
        return {"case_id": case["id"]}

    def evaluate(rows, thresholds, deployment, output, mode):
        assert deployment == "judge"
        assert ("tool_call_accuracy" in thresholds) == (mode == "live_sources")
        return [
            {"datasource_item_id": i, "status": "completed", "results": [
                {"name": key, "type": "azure_ai_evaluator", "score": value, "passed": True}
                for key, value in thresholds.items()
            ]}
            for i in range(len(rows))
        ]

    class Credential(Resource):
        async def __aenter__(self):
            if failure == "auth":
                raise ValueError("auth failure")
            return self

    class NeverToolbox:
        def __init__(self, *args, **kwargs):
            pytest.fail("Supplied-only mode must not construct or discover a toolbox.")

    monkeypatch.setattr("azure.identity.aio.AzureCliCredential", Credential)
    monkeypatch.setattr("azure.ai.projects.aio.AIProjectClient", Resource)
    monkeypatch.setattr(
        "agent_framework_foundry_hosting.FoundryToolbox",
        NeverToolbox if mode == "supplied_sources_only" else Resource,
    )
    monkeypatch.setattr("agent_framework.foundry.FoundryChatClient", Transport)
    monkeypatch.setattr("tools.hosted_evaluation.evaluator_row", row)
    demo = LiveDemo(config, SimpleNamespace(model_version=lambda _: "1", evaluate=evaluate))
    if failure and failure != "wrong-status":
        if failure == "budget":
            demo.calls = 100
        with pytest.raises(
            ValueError, match="budget exhausted|Replayed model|Invalid JSON|supplied content|auth failure",
        ):
            asyncio.run(demo.evaluate("Do not infer facts.", tmp_path))
        if failure == "budget":
            assert not observed
        return
    if failure == "wrong-status":
        expectations = [case["expected_status"] for case in demo.cases]
        improvements = []

        async def improve(candidate, feedback):
            improvements.append(feedback)
            supplied = feedback["deterministic"] if mode == "supplied_sources_only" else feedback["deterministic"][2:]
            assert all(not item["status_matches"] for item in supplied)
            assert set(feedback["judges"]) == (
                {"supplied_sources"} if mode == "supplied_sources_only" else {"live_sources", "supplied_sources"}
            )
            return ""

        result = asyncio.run(loop(demo.evaluate, improve, tmp_path / "wrong-status"))
        assert result["status"] == "no_safe_improvement"
        assert len(improvements) == 1
        assert [case["expected_status"] for case in demo.cases] == expectations
        return
    asyncio.run(demo.evaluate("Do not infer facts.", tmp_path))
    count = 3 if mode == "supplied_sources_only" else 5
    assert len(reports) == count
    assert count <= len(observed) == demo.calls <= count * 2  # Includes existing one-shot evidence repair.
    assert len(demo.seen_response_ids) == demo.calls
    assert len({r.execution.execution_id for r in reports}) == count
    assert len(list(tmp_path.glob("*-evaluation.json"))) == count
    if mode == "supplied_sources_only":
        assert demo.coverage["excluded_case_ids"] == ["order-sync-retry", "order-sync-information-missing"]
        assert demo.coverage["tool_call_accuracy"] == "not_evaluated"
        assert not (tmp_path / "live_sources-inputs.json").exists()


def test_cancellation_records_failure(tmp_path):
    async def evaluate(candidate, output):
        raise asyncio.CancelledError()

    async def improve(candidate, feedback):
        pytest.fail("cancelled evaluations must stop")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop(evaluate, improve, tmp_path / "run", {"source_commit": "test"}))
    assert json.loads((tmp_path / "run" / "decision.json").read_text())["status"] == "blocked"
    assert (tmp_path / "run" / "manifest.json").is_file()


def test_optimizer_is_a_bounded_model_call_not_a_file_editor():
    from documentation_agent.settings import AssessmentSettings

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_text="Do not infer facts.")

    demo = object.__new__(LiveDemo)
    demo.settings = AssessmentSettings(
        project_endpoint="https://example.services.ai.azure.com/api/projects/isolated",
        toolbox_endpoint="https://example.services.ai.azure.com/api/projects/isolated/toolboxes/read/mcp?api-version=v1",
        model="agent", model_version="1", ado_project="demo", ado_wiki="demo", auth_mode="azure_cli",
    )
    demo.config = SimpleNamespace(optimizer_deployment="optimizer")
    demo.cloud = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    assert asyncio.run(demo.improve("old", {"failure": "groundedness"})) == "Do not infer facts."
    assert calls[0]["model"] == "optimizer"
    assert calls[0]["max_output_tokens"] == 3000
    assert calls[0]["store"] is False
    assert "Never alter evaluator rules" in calls[0]["instructions"]
    assert json.loads(calls[0]["input"])["current_guidance"] == "old"


def test_partial_pass_never_claims_full_suite_quality(tmp_path):
    async def evaluate(candidate, output):
        return True, 1.0, {}

    async def improve(candidate, feedback):
        pytest.fail("passing partial demo must stop")

    coverage = {
        "mode": "supplied_sources_only",
        "selected_case_ids": [
            "order-sync-version-isolation", "order-sync-dead-letter-stub", "order-sync-wiki-unavailable",
        ],
        "excluded_case_ids": ["order-sync-retry", "order-sync-information-missing"],
        "tool_call_accuracy": "not_evaluated",
    }
    result = asyncio.run(loop(evaluate, improve, tmp_path / "partial", {"coverage": coverage}))
    assert result["status"] == "partial_passed"
    assert result["full_suite_passed"] is False
    assert result["coverage"] == coverage
    summary = (tmp_path / "partial" / "summary.md").read_text()
    assert "supplied_sources_only" in summary
    assert all(case in summary for case in coverage["excluded_case_ids"])


@pytest.mark.parametrize("unexpected", ["TOOLBOX_ENDPOINT", "DOCUMENTATION_MODEL_GATEWAY_ENDPOINT", "GITHUB_TOKEN"])
def test_partial_settings_reject_unused_source_credentials_and_endpoints(unexpected):
    from tools.eval_loop import SuppliedSettings

    with pytest.raises(ValueError):
        SuppliedSettings.model_validate({
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://isolated.services.ai.azure.com/api/projects/eval",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "candidate",
            "DOCUMENTATION_MODEL_VERSION": "2026-03-17",
            "DOCUMENTATION_ADO_PROJECT": "domain-only", "DOCUMENTATION_ADO_WIKI": "domain-only",
            "DOCUMENTATION_AUTH_MODE": "azure_cli", unexpected: "not-allowed",
        })


def test_reviewed_partial_configuration_needs_no_toolbox():
    from tools.eval_loop import SuppliedSettings, runtime_settings

    config = LoopConfig.model_validate_json(
        Path("infra/isolated-evaluation/supplied-demo-config.json").read_text(),
    )
    assert config.mode == "supplied_sources_only"
    settings = runtime_settings(config)
    assert isinstance(settings, SuppliedSettings)
    assert "TOOLBOX_ENDPOINT" not in config.settings
    assert settings.project_endpoint != config.serving_project_endpoint
    assert settings.model_version == config.evaluator_version == config.optimizer_version == "2026-03-17"
    assert config.observed_model == "gpt-5.4-mini-2026-03-17"
    assert config.model_copy(update={"mode": "full_suite"}).mode == "full_suite"
    with pytest.raises(ValueError, match="toolbox_endpoint"):
        runtime_settings(config.model_copy(update={"mode": "full_suite"}))
