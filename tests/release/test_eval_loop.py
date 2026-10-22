import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tools.eval_loop import THRESHOLDS, LiveDemo, LoopConfig, loop, main, quality


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
def test_five_total_candidates_and_real_revisions(tmp_path, pass_at, expected, calls):
    evaluated, optimized = [], []

    async def evaluate(candidate, output):
        evaluated.append(candidate)
        return len(evaluated) >= pass_at, len(evaluated) / 5, {"failure": "groundedness"}

    async def improve(candidate, feedback):
        optimized.append(feedback)
        return candidate + "Better instructions.\n"

    output = tmp_path / "run"
    result = asyncio.run(loop(evaluate, improve, output))
    assert result["status"] == expected
    assert len(evaluated) == calls
    assert len(set(evaluated)) == calls
    assert len(optimized) == calls - 1
    assert result["best_attempt"] == calls
    assert result["promotion_eligible"] is False
    assert json.loads((output / "decision.json").read_text()) == result
    assert (output / "best-instructions.txt").read_text() == evaluated[-1]


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


@pytest.mark.parametrize("failure", [None, "budget", "replay"])
def test_actual_agent_sdk_path_uses_new_guidance_and_bounded_fresh_calls(monkeypatch, tmp_path, failure):
    """Offline transport double; this test does not assert semantic agent quality."""
    from agent_framework import (
        BaseChatClient,
        ChatMiddlewareLayer,
        ChatResponse,
        Content,
        FunctionInvocationLayer,
        Message,
    )

    settings = {
        "DOCUMENTATION_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/isolated",
        "TOOLBOX_ENDPOINT": "https://example.services.ai.azure.com/api/projects/isolated/toolboxes/read/mcp?api-version=v1",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "agent", "DOCUMENTATION_MODEL_VERSION": "1",
        "DOCUMENTATION_ADO_PROJECT": "demo", "DOCUMENTATION_ADO_WIKI": "demo",
        "DOCUMENTATION_AUTH_MODE": "azure_cli",
    }
    config = LoopConfig(
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
            return ChatResponse(
                messages=[Message("assistant", [Content.from_text(json.dumps({
                    "documentation_status": "insufficient_information",
                    "findings": [], "proposed_changes": [],
                    "missing_information": [{"description": "Unknown.", "expected_source": "wiki"}],
                    "evidence": [], "confidence": 0.5, "requires_human_review": True,
                }))])],
                response_id="same" if failure == "replay" else str(uuid4()), model="agent", finish_reason="stop",
            )

    def row(case, payload, report, definition):
        assert definition["environment_variables"] == settings
        assert "Do not infer facts." in report.execution.instructions
        assert report.execution.model_calls[0]["status"] == "completed"
        reports.append(report)
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

    monkeypatch.setattr("azure.identity.aio.AzureCliCredential", Resource)
    monkeypatch.setattr("azure.ai.projects.aio.AIProjectClient", Resource)
    monkeypatch.setattr("agent_framework_foundry_hosting.FoundryToolbox", Resource)
    monkeypatch.setattr("agent_framework.foundry.FoundryChatClient", Transport)
    monkeypatch.setattr("tools.hosted_evaluation.evaluator_row", row)
    demo = LiveDemo(config, SimpleNamespace(model_version=lambda _: "1", evaluate=evaluate))
    if failure:
        if failure == "budget":
            demo.calls = 100
        with pytest.raises(ValueError, match="budget exhausted|Replayed model"):
            asyncio.run(demo.evaluate("Do not infer facts.", tmp_path))
        if failure == "budget":
            assert not observed
        return
    asyncio.run(demo.evaluate("Do not infer facts.", tmp_path))
    assert len(reports) == 5
    assert 5 <= len(observed) == demo.calls <= 10  # Includes the existing one-shot evidence repair.
    assert len(demo.seen_response_ids) == demo.calls
    assert len({r.execution.execution_id for r in reports}) == 5
    assert len(list(tmp_path.glob("*-evaluation.json"))) == 5


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
