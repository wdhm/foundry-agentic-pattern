import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tools.eval_loop import (
    THRESHOLDS,
    LiveDemo,
    LoopConfig,
    LoopTelemetry,
    OperationalError,
    Reason,
    Stage,
    http_failure,
    loop,
    main,
    quality,
    safe_failure,
    schema_parse_failure,
)


@pytest.mark.parametrize("stage", ["setup", "evaluation"])
def test_sensitive_exception_never_reaches_logs_or_failure_artifacts(tmp_path, monkeypatch, capsys, stage):
    from pydantic import ValidationError

    secret = "SENSITIVE_SOURCE_FRAGMENT"
    validation = ValidationError.from_exception_data("Sensitive", [{
        "type": "value_error", "loc": (secret, 2), "input": secret,
        "ctx": {"error": ValueError(secret)},
    }])
    wrapped = RuntimeError(secret, validation)
    wrapped.__cause__ = validation
    assert safe_failure(wrapped) == {
        "exception": "RuntimeError",
        "validation": [{"location": ["<field>", 2], "type": "value_error"}],
    }
    output = tmp_path / "run"
    summary = tmp_path / "actions.md"
    monkeypatch.setenv("EVAL_LOOP_APPROVED", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    config = tmp_path / "config.json"
    config.write_text("{}")

    async def evaluate(candidate, attempt):
        raise wrapped

    async def improve(candidate, feedback):
        pytest.fail("schema-invalid output must not reach optimizer")

    def fail_config(*args, **kwargs):
        if stage == "evaluation":
            asyncio.run(loop(evaluate, improve, output))
        raise wrapped

    monkeypatch.setattr(LoopConfig, "model_validate_json", fail_config)
    assert main(["--config", str(config), "--output", str(output), "--execute-approved-isolated"]) == 1
    captured = capsys.readouterr()
    diagnostic = json.loads(captured.out.removeprefix("eval-loop diagnostics: "))
    assert diagnostic["exception"] == "RuntimeError"
    assert diagnostic["reason"] == "unknown"
    assert diagnostic["counters"]["completed_candidates"] == 0
    assert secret not in captured.out + captured.err
    assert "RuntimeError" in captured.err
    assert secret not in summary.read_text()
    for path in output.rglob("*"):
        if path.is_file():
            assert secret not in path.read_text()
    decision = json.loads((output / "decision.json").read_text())
    assert decision["status"] == "blocked"
    assert decision["attempts"] == []
    assert decision["error"] == safe_failure(wrapped)


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


def test_only_direct_sdk_analysis_parse_failure_is_repairable():
    from agent_framework.exceptions import ChatClientException
    from pydantic import ValidationError

    schema = ValidationError.from_exception_data("AnalysisOutput", [])
    wrapped = ChatClientException("redacted", schema)
    assert not schema_parse_failure(wrapped)  # Arguments alone do not prove SDK parsing.
    wrapped.__cause__ = schema
    assert schema_parse_failure(wrapped)
    wrapped.__cause__ = ValidationError.from_exception_data("Settings", [])
    assert not schema_parse_failure(wrapped)
    other = RuntimeError("operational failure")
    other.__cause__ = schema
    wrapped.__cause__ = other
    assert not schema_parse_failure(wrapped)
    wrapped.__cause__ = schema
    http = RuntimeError("http")
    http.status_code = 403
    http.response = SimpleNamespace(headers={})
    wrapped.__context__ = http
    assert not schema_parse_failure(wrapped)


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
    with pytest.raises(OperationalError) as caught:
        quality(value, 1, THRESHOLDS)
    assert caught.value.stage == Stage.JUDGE_VALIDATION
    assert caught.value.reason == {
        "missing": Reason.JUDGE_RESULTS, "duplicate": Reason.JUDGE_ROWS, "nan": Reason.JUDGE_SCORE,
        "error": Reason.JUDGE_FAILED, "boolean": Reason.JUDGE_SCORE, "label": Reason.JUDGE_SCORE,
    }[mutation]


@pytest.mark.parametrize("pass_at,expected,calls", [(1, "passed", 1), (3, "passed", 3), (9, "exhausted", 5)])
@pytest.mark.parametrize("mode", ["full_suite", "supplied_sources_only"])
def test_five_total_candidates_and_real_revisions(tmp_path, pass_at, expected, calls, mode):
    evaluated, optimized = [], []
    telemetry = LoopTelemetry()

    async def evaluate(candidate, output):
        evaluated.append(candidate)
        return len(evaluated) >= pass_at, len(evaluated) / 5, {"failure": "groundedness"}

    async def improve(candidate, feedback):
        optimized.append(feedback)
        return candidate + "Better instructions.\n"

    output = tmp_path / "run"
    result = asyncio.run(loop(evaluate, improve, output, {"coverage": {"mode": mode}}, telemetry))
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
    assert telemetry.attempt_number == telemetry.completed_candidates == calls
    # Generic callbacks are not assumed to have dispatched model or judge API calls.
    assert telemetry.optimizer_attempts == telemetry.judge_groups_submitted == 0


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
    with pytest.raises(ValueError, match="isolation_required"):
        LiveDemo(config, None)


@pytest.mark.parametrize("failure", [
    None, "budget", "replay", "wrong-status", "schema", "source", "auth",
    "model-version", "observed-model", "incomplete", "row",
])
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
                response_id="same" if failure == "replay" else str(uuid4()),
                model="unexpected-model" if failure == "observed-model" else "agent",
                finish_reason="length" if failure == "incomplete" else "stop",
            )

    def row(case, payload, report, definition):
        if failure == "row":
            raise ValueError("SENSITIVE_ROW_PAYLOAD")
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

    def evaluate(rows, thresholds, deployment, output, mode, *, on_event):
        assert deployment == "judge"
        assert ("tool_call_accuracy" in thresholds) == (mode == "live_sources")
        on_event("submitted")
        on_event("completed")
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
    # These transport doubles do not perform live reads; live evidence is tested separately.
    monkeypatch.setattr("documentation_agent.assessment.AssessmentAgent.analysis_problems", lambda *args: [])
    monkeypatch.setattr("tools.hosted_evaluation.evaluator_row", row)
    demo = LiveDemo(config, SimpleNamespace(
        model_version=lambda _: "2" if failure == "model-version" else "1", evaluate=evaluate,
    ))
    if failure and failure != "wrong-status":
        if failure == "budget":
            demo.calls = 100
        with pytest.raises(
            ValueError, match=(
                "request_budget_exhausted|response_replay|Invalid JSON|evidence_repair_exhausted|auth failure"
                "|model_version_mismatch|incomplete_execution_or_unexpected_model|incomplete_response"
                "|SENSITIVE_ROW_PAYLOAD"
            ),
        ) as caught:
            asyncio.run(demo.evaluate("Do not infer facts.", tmp_path))
        snapshot = demo.telemetry.snapshot(caught.value)
        expected = {
            "budget": (Stage.REQUEST, Reason.REQUEST_BUDGET),
            "replay": (Stage.RESPONSE, Reason.RESPONSE_REPLAY),
            "source": (Stage.EVIDENCE, Reason.EVIDENCE_REPAIR),
            "model-version": (Stage.MODEL_CHECK, Reason.MODEL_VERSION_MISMATCH),
            "observed-model": (Stage.CASE_RESULT, Reason.EXECUTION_MODEL),
            "incomplete": (Stage.RESPONSE, Reason.INCOMPLETE_RESPONSE),
            "schema": (Stage.CASE_RESULT, "unknown"),
            "auth": (Stage.INVOCATION, "unknown"),
            "row": (Stage.SCORER, "unknown"),
        }
        assert (snapshot["stage"], snapshot["reason"]) == expected[failure]
        counts = snapshot["counters"]
        assert counts["completed_candidates"] == 0
        assert counts["completed_cases"] == (
            1 if failure == "replay" else 2 if failure == "source" and mode == "full_suite" else 0
        )
        assert counts["judge_groups_submitted"] == counts["optimizer_attempts"] == 0
        assert "SENSITIVE_ROW_PAYLOAD" not in json.dumps(snapshot)
        if failure == "budget":
            assert not observed
            assert counts["counted_model_requests"] == 101
            assert counts["dispatched_model_requests"] == counts["repair_attempts"] == 0
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


@pytest.mark.parametrize("failure", [None, "operational", "incomplete", "budget"])
def test_optimizer_is_a_bounded_model_call_not_a_file_editor(failure):
    from documentation_agent.settings import AssessmentSettings

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if failure == "operational":
            raise RuntimeError("SENSITIVE_OPTIMIZER_OUTPUT")
        return SimpleNamespace(
            status="failed" if failure == "incomplete" else "completed", output_text="Do not infer facts.",
        )

    demo = object.__new__(LiveDemo)
    demo.telemetry = LoopTelemetry()
    demo.settings = AssessmentSettings(
        project_endpoint="https://example.services.ai.azure.com/api/projects/isolated",
        toolbox_endpoint="https://example.services.ai.azure.com/api/projects/isolated/toolboxes/read/mcp?api-version=v1",
        model="agent", model_version="1", ado_project="demo", ado_wiki="demo", auth_mode="azure_cli",
    )
    demo.config = SimpleNamespace(optimizer_deployment="optimizer")
    demo.cloud = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    feedback = {"failure": "x" * 150001 if failure == "budget" else "groundedness"}
    if failure:
        with pytest.raises((RuntimeError, OperationalError)) as caught:
            asyncio.run(demo.improve("old", feedback))
        snapshot = demo.telemetry.snapshot(caught.value)
        assert snapshot["stage"] == Stage.OPTIMIZER
        assert snapshot["reason"] == {
            "operational": "unknown", "incomplete": Reason.OPTIMIZER_INCOMPLETE,
            "budget": Reason.OPTIMIZER_BUDGET,
        }[failure]
        assert snapshot["counters"]["optimizer_attempts"] == int(failure != "budget")
        assert snapshot["counters"]["optimizer_completed"] == 0
        assert "SENSITIVE_OPTIMIZER_OUTPUT" not in json.dumps(snapshot)
        return
    assert asyncio.run(demo.improve("old", feedback)) == "Do not infer facts."
    assert calls[0]["model"] == "optimizer"
    assert calls[0]["max_output_tokens"] == 3000
    assert calls[0]["store"] is False
    assert "Never alter evaluator rules" in calls[0]["instructions"]
    assert json.loads(calls[0]["input"])["current_guidance"] == "old"
    assert demo.telemetry.optimizer_attempts == demo.telemetry.optimizer_completed == 1


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


@pytest.mark.parametrize("sequence", [
    ("schema", "valid"), ("schema", "schema"), ("http",), ("timeout",),
    ("schema", "evidence"), ("evidence", "schema"), ("evidence", "valid"),
])
def test_real_foundry_sdk_schema_repair_is_single_fresh_bounded_invocation(
    monkeypatch, tmp_path, capsys, sequence,
):
    """Use real Foundry/OpenAI parsing over an offline HTTP transport, never a model service."""
    import httpx
    from openai import AsyncOpenAI

    from tools.eval_loop import REPAIR_INSTRUCTIONS

    requests, clients = [], []
    secret = "SENSITIVE_INVALID_OUTPUT"

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["store"] is False
        assert not {"previous_response_id", "conversation"} & body.keys()
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        outcome = sequence[len(requests) - 1]
        if outcome == "http":
            return httpx.Response(403, json={"error": {"code": "Forbidden", "message": secret}})
        if outcome == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        answer = {
            "documentation_status": "insufficient_information", "findings": [], "proposed_changes": [],
            "missing_information": [{"description": "Unknown.", "expected_source": "wiki"}],
            "evidence": [], "confidence": 0.5, "requires_human_review": True,
        }
        if outcome == "schema":
            answer.update(requires_human_review=False, proposed_changes=[{
                "target_page": "demo", "target_section": "demo", "proposed_content": secret,
                "evidence_refs": ["support"],
            }], evidence=[{
                "id": "support", "source": "wiki", "uri": "https://invalid.example/source",
                "version": "wiki-etag-1", "excerpt": secret,
            }])
        elif outcome == "evidence":
            answer["evidence"] = [{
                "id": "unsupported", "source": "wiki", "uri": "https://invalid.example/source",
                "version": "wiki-etag-1", "excerpt": secret,
            }]
        return httpx.Response(200, json={
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "model": "agent", "status": "completed",
            "output": [{"type": "message", "id": f"msg_{len(requests)}", "role": "assistant",
                        "status": "completed", "content": [{
                            "type": "output_text", "text": json.dumps(answer), "annotations": [],
                        }]}],
            "parallel_tool_calls": False, "tool_choice": "none", "tools": [],
        })

    class Resource:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get_openai_client(self, **kwargs):
            client = AsyncOpenAI(
                api_key="offline-test-only", base_url="https://offline.example/api/projects/eval/openai/v1",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
            clients.append(client)
            return client

    monkeypatch.setattr("azure.identity.aio.AzureCliCredential", Resource)
    monkeypatch.setattr("azure.ai.projects.aio.AIProjectClient", Resource)
    config = LoopConfig(
        mode="supplied_sources_only", observed_model="agent",
        settings={
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://isolated.example/api/projects/eval",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "agent", "DOCUMENTATION_MODEL_VERSION": "1",
            "DOCUMENTATION_ADO_PROJECT": "demo", "DOCUMENTATION_ADO_WIKI": "demo",
            "DOCUMENTATION_AUTH_MODE": "azure_cli",
        },
        evaluator_deployment="judge", evaluator_version="1",
        optimizer_deployment="optimizer", optimizer_version="1",
        isolation_review_reference="offline-test",
        serving_project_endpoint="https://serving.example/api/projects/prod",
    )
    judges = []

    def evaluate(rows, thresholds, *args, on_event):
        on_event("submitted")
        on_event("completed")
        judges.append(rows)
        return [{
            "datasource_item_id": i, "status": "completed", "results": [
                {"name": name, "type": "azure_ai_evaluator", "score": score, "passed": True}
                for name, score in thresholds.items()
            ],
        } for i in range(len(rows))]

    demo = LiveDemo(config, SimpleNamespace(model_version=lambda _: "1", evaluate=evaluate))
    demo.cases = demo.cases[:1]
    output = tmp_path / "run"

    async def improve(*args):
        pytest.fail("Operational failure must never call optimizer")

    if sequence[-1] == "valid":
        output.mkdir()
        asyncio.run(demo.evaluate("", output))
        assert len(judges) == 1
    else:
        with pytest.raises(Exception) as error:
            asyncio.run(loop(demo.evaluate, improve, output))
        decision = json.loads((output / "decision.json").read_text())
        assert decision["status"] == "blocked"
        assert decision["attempts"] == []
        assert not judges
        if sequence[-1] == "schema":
            assert safe_failure(error.value)["validation"]
            assert error.value.__cause__.errors(include_input=False)[0]["type"] == "value_error"
    assert len(requests) == len(sequence) == demo.calls
    counts = demo.telemetry.snapshot()["counters"]
    assert counts["counted_model_requests"] == counts["dispatched_model_requests"] == len(sequence)
    assert counts["repair_attempts"] == len(sequence) - 1
    assert counts["completed_model_requests"] == sequence.count("valid") + sequence.count("evidence")
    assert counts["completed_cases"] == int(sequence[-1] == "valid")
    assert counts["judge_groups_submitted"] == counts["judge_groups_completed"] == len(judges)
    assert len(clients) == len(sequence)
    assert all(client.is_closed() for client in clients)
    if len(requests) == 2:
        assert REPAIR_INSTRUCTIONS.strip() in requests[1]["instructions"]
        assert secret not in json.dumps(requests[1])
        assert requests[0]["input"] == requests[1]["input"]
    invocations = sorted(output.rglob("*-invocation-*.json"))
    assert len(invocations) == len(sequence)
    for index, path in enumerate(invocations):
        entry = json.loads(path.read_text())
        assert entry["request_count_before"] == index
        assert entry["request_count_after"] == index + 1
        if sequence[index] == "schema":
            assert entry["status"] == "schema_invalid"
            call = entry["execution"]["model_calls"][0]
            assert call["status"] == "schema_invalid"
            assert "output" not in call and "response_id" not in call
            assert secret not in path.read_text()
        if sequence[index] == "evidence":
            assert entry["status"] == "completed"  # Parsed successfully; only source verification failed.
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    for path in output.rglob("*"):
        if path.name in {"decision.json", "summary.md"}:
            assert secret not in path.read_text()


def test_source_integrity_check_exception_does_not_enter_correction():
    from tools.eval_loop import candidate_with_repair

    calls = []

    async def invoke(correction):
        calls.append(correction)
        return "output"

    def check(value):
        raise ValueError("source integrity violation")

    with pytest.raises(ValueError, match="source integrity violation"):
        asyncio.run(candidate_with_repair(invoke, check))
    assert calls == [False]


def test_safe_snapshot_is_a_closed_projection_not_exception_message_matching():
    secret = "SENSITIVE_INPUT_OR_REASON"
    telemetry = LoopTelemetry(
        mode="supplied_sources_only", selected_case_ids=("order-sync-version-isolation", secret),
    )
    telemetry.stage = secret
    telemetry.status = secret
    telemetry.failure_reason = secret
    telemetry.counted_model_requests = secret
    telemetry.excluded_case_ids = (secret,)
    telemetry.untrusted_feedback = {"source": secret}
    error = ValueError("incomplete_execution_or_unexpected_model " + secret)
    snapshot = telemetry.snapshot(error)
    assert snapshot["stage"] == snapshot["reason"] == snapshot["status"] == "unknown"
    assert snapshot["exception"] == "ValueError"
    assert snapshot["counters"]["counted_model_requests"] == 0
    assert snapshot["coverage"]["selected_case_ids"] == ["order-sync-version-isolation"]
    assert secret not in json.dumps(snapshot)
    assert safe_failure(error) == {"exception": "ValueError"}
    with pytest.raises(TypeError):
        OperationalError(Stage.REQUEST, secret)


def test_main_publishes_only_closed_guard_reason_and_counters(tmp_path, monkeypatch, capsys):
    secret = "SENSITIVE_EXCEPTION_MESSAGE"

    def fail(*args, **kwargs):
        error = OperationalError(Stage.CASE_RESULT, Reason.EXECUTION_MODEL)
        error.args = (secret,)
        raise error

    monkeypatch.setenv("EVAL_LOOP_APPROVED", "true")
    monkeypatch.setattr(LoopConfig, "model_validate_json", fail)
    config = tmp_path / "config.json"
    config.write_text("{}")
    output = tmp_path / "run"
    assert main(["--config", str(config), "--output", str(output), "--execute-approved-isolated"]) == 1
    captured = capsys.readouterr()
    snapshot = json.loads(captured.out.removeprefix("eval-loop diagnostics: "))
    assert (snapshot["stage"], snapshot["reason"]) == (Stage.CASE_RESULT, Reason.EXECUTION_MODEL)
    assert snapshot["status"] == "blocked"
    assert not any(snapshot["counters"].values())
    assert secret not in captured.out + captured.err
    assert all(secret not in path.read_text() for path in output.iterdir())


def test_later_candidate_failure_retains_completed_candidate_accounting(tmp_path):
    telemetry = LoopTelemetry()

    async def evaluate(candidate, output):
        if candidate:
            raise OperationalError(Stage.CASE_RESULT, Reason.EXECUTION_MODEL)
        return False, 0.5, {}

    async def improve(candidate, feedback):
        return "changed guidance"

    with pytest.raises(OperationalError) as caught:
        asyncio.run(loop(evaluate, improve, tmp_path / "run", telemetry=telemetry))
    snapshot = telemetry.snapshot(caught.value)
    assert snapshot["status"] == "blocked"
    assert snapshot["counters"]["attempt_number"] == 2
    assert snapshot["counters"]["completed_candidates"] == 1
    assert snapshot["counters"]["completed_cases"] == snapshot["counters"]["attempt_completed_cases"] == 0
    assert snapshot["counters"]["optimizer_attempts"] == snapshot["counters"]["dispatched_model_requests"] == 0


@pytest.mark.parametrize("failure", ["definition", "submission", "run", "outputs", None])
def test_judge_counters_follow_actual_run_submission_and_completion(tmp_path, failure):
    from tools.release import FoundryEvaluation

    secret = "SENSITIVE_JUDGE_RESULT"
    telemetry = LoopTelemetry()

    class Dump(SimpleNamespace):
        def model_dump(self):
            return vars(self)

    def definition(**kwargs):
        if failure == "definition":
            raise ValueError(secret)
        return Dump(id="eval-id")

    def submit(**kwargs):
        if failure == "submission":
            raise ValueError(secret)
        return Dump(id="run-id", status="failed" if failure == "run" else "completed", error=None)

    def outputs(**kwargs):
        if failure == "outputs":
            raise ValueError(secret)
        return []

    cloud = FoundryEvaluation(None, SimpleNamespace(evals=SimpleNamespace(
        create=definition, runs=SimpleNamespace(create=submit, output_items=SimpleNamespace(list=outputs)),
    )))
    error = None
    try:
        cloud.evaluate([], {"groundedness": 3.0}, "judge", tmp_path, "supplied_sources",
                       on_event=telemetry.judge_event)
    except ValueError as exc:
        error = exc
    assert (error is not None) == (failure is not None)
    snapshot = telemetry.snapshot(error)
    assert snapshot["counters"]["judge_groups_submitted"] == int(failure not in {"definition", "submission"})
    assert snapshot["counters"]["judge_groups_completed"] == int(failure in {None, "outputs"})
    assert snapshot["counters"]["completed_candidates"] == snapshot["counters"]["completed_cases"] == 0
    assert snapshot["stage"] == {
        "definition": Stage.JUDGE_DEFINITION, "submission": Stage.JUDGE_SUBMISSION,
        "run": Stage.JUDGE_POLLING, "outputs": Stage.JUDGE_OUTPUTS, None: Stage.JUDGE_OUTPUTS,
    }[failure]
    assert snapshot["reason"] == (Reason.JUDGE_RUN if failure == "run" else "unknown")
    assert secret not in json.dumps(snapshot)
