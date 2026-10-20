"""Canonical hosted evaluation transport and observed-record to built-in evaluator adapters."""

import hashlib
import json
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from contracts.evaluation import EvaluationRequest, EvaluationResponse, SourceSnapshot, SuppliedStandard
from contracts.v1 import AnalysisOutput, AssessmentTask, assemble_result
from tools.cli import structured_text
from tools.hosted import HostedArtifact, hosted_response
from tools.release_sources import verify_sources


def evaluation_request(
    case: dict[str, Any], scope: Literal["change_review", "information_review"],
) -> EvaluationRequest:
    task = AssessmentTask(question=case["question"], scope=scope)
    if case["request"].task is not None and case["request"].task != task:
        raise ValueError("Reviewed scenario task conflicts with the existing canonical request.task.")
    request = case["request"].model_copy(
        update={"task": task}
    )
    values: dict[str, Any] = {
        "interface_version": "1.0.0", "source_mode": case["mode"], "request": request,
    }
    if case["mode"] == "supplied_sources":
        values["standard"] = SuppliedStandard(
            content=case["rules"], sha256=hashlib.sha256(case["rules"].encode()).hexdigest(),
        )
        values["sources"] = [
            SourceSnapshot(
                id=f"source-{index}", availability="available", **source,
                sha256=hashlib.sha256(source["content"].encode()).hexdigest(),
            )
            for index, source in enumerate(case["sources"])
        ]
    # Revalidate the task-aware copy through the authoritative cross-field validators.
    return EvaluationRequest.model_validate_json(EvaluationRequest(**values).model_dump_json())


def expected_instructions(definition: dict[str, Any], mode: str) -> str:
    from documentation_agent.assessment import AssessmentAgent
    from documentation_agent.evaluation import supplied_instructions
    from documentation_agent.settings import AssessmentSettings

    settings = AssessmentSettings.from_environment(definition["environment_variables"])
    return (
        AssessmentAgent(settings).instructions if mode == "live_sources"
        else supplied_instructions(settings)
    )


def validate_report(
    raw: dict[str, Any], payload: EvaluationRequest, artifact: HostedArtifact,
    definition: dict[str, Any], lineage: dict[str, Any], observed_model: str,
) -> EvaluationResponse:
    if any(item.get("type") not in {"message", "reasoning"} for item in raw.get("output", [])):
        raise ValueError("Evaluation outer response contains unexpected tools/approval output.")
    report = EvaluationResponse.model_validate_json(structured_text(raw))
    record = report.execution
    if (
        record.request_id != payload.request.request_id
        or record.correlation_id != payload.request.correlation_id
        or report.result.request_id != payload.request.request_id
        or record.source_mode != payload.source_mode
        or record.status != "completed"
    ):
        raise ValueError("Evaluation request/result/execution correlation or completion mismatch.")
    if record.platform_session_id is not None and record.platform_session_id != lineage["agent_session_id"]:
        raise ValueError("Observed platform session differs from the outer session.")
    instructions = expected_instructions(definition, payload.source_mode)
    provenance = artifact.runtime_provenance.model_copy(
        update={"prompt_version": "sha256:" + hashlib.sha256(instructions.encode()).hexdigest()}
    )
    if record.instructions != instructions or report.result.provenance != provenance:
        raise ValueError("Evaluation instructions/provenance differ from the reviewed packaged runtime.")
    if record.sources != payload.sources or record.standard != payload.standard:
        raise ValueError("Evaluation source isolation context differs from the submitted bundle.")
    if not record.model_calls:
        raise ValueError("Evaluation has no observed model calls.")
    response_ids = set()
    for index, call in enumerate(record.model_calls):
        if (
            call.get("index") != index or call.get("status") != "completed"
            or not isinstance(call.get("response_id"), str) or not call["response_id"].strip()
            or call["response_id"] in response_ids
            or call.get("model") != observed_model
            or call.get("finish_reason") not in {"stop", "tool_calls"}
            or not isinstance(call.get("input"), list) or not isinstance(call.get("output"), list)
        ):
            raise ValueError("Evaluation model-call capture is incomplete, duplicated or inconsistent.")
        for message in [*call["input"], *call["output"]]:
            if (
                not isinstance(message, dict) or not isinstance(message.get("content"), list)
                or not message["content"] or any(not isinstance(item, dict) for item in message["content"])
            ):
                raise ValueError("Malformed observed model messages/content.")
        response_ids.add(call["response_id"])
    if payload.source_mode == "supplied_sources" and (record.tool_calls or record.tool_schemas):
        raise ValueError("Supplied-source evaluation unexpectedly used/discovered tools.")
    if payload.source_mode == "live_sources" and (not record.tool_calls or not record.tool_schemas):
        raise ValueError("Live evaluation needs observed tool calls and discovered schemas.")
    return report


def arguments(value: Any) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("Observed tool arguments must be a JSON object.")
    return parsed


def evaluator_row(
    case: dict[str, Any], payload: EvaluationRequest, report: EvaluationResponse,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Use actual model call IDs and policy results, never synthetic calls or gold text."""
    from documentation_agent.read_policy import READ_TOOLS, require_read
    from documentation_agent.settings import AssessmentSettings

    record = report.execution
    settings = AssessmentSettings.from_environment(definition["environment_variables"])
    schemas: dict[str, dict[str, Any]] = {}
    for schema in record.tool_schemas:
        name = schema.get("name")
        if (
            name not in READ_TOOLS or name in schemas or not isinstance(schema.get("parameters"), dict)
            or not isinstance(schema.get("description", ""), str)
        ):
            raise ValueError("Unexpected, duplicated or malformed discovered read-tool schema.")
        try:
            Draft202012Validator.check_schema(schema["parameters"])
        except SchemaError as exc:
            raise ValueError("Malformed discovered read-tool JSON schema.") from exc
        schemas[name] = schema
    if payload.source_mode == "live_sources" and set(schemas) != set(READ_TOOLS):
        raise ValueError("Live evaluation did not discover all canonical read tools.")

    first_input = record.model_calls[0]["input"]
    expected = payload.request.model_dump(mode="json") if payload.source_mode == "live_sources" else payload.model_dump(
        mode="json"
    )
    user = [message for message in first_input if message.get("role") == "user"]
    if len(user) != 1 or len(user[0].get("content", [])) != 1:
        raise ValueError("First model request must contain the single actual evaluation input.")
    content = user[0]["content"][0]
    if content.get("type") != "text" or json.loads(content.get("text", "")) != expected:
        raise ValueError("Observed model input differs from the canonical evaluation request.")
    for message in first_input:
        if message.get("role") != "user" and (
            message.get("role") not in {"system", "developer"}
            or any(item.get("type") != "text" or item.get("text") != record.instructions
                   for item in message.get("content", []))
        ):
            raise ValueError("Unexpected prior conversation or instruction in first model input.")

    calls: list[dict[str, Any]] = []
    response: list[dict[str, Any]] = []
    seen_ids = set()
    model_results: dict[str, str] = {}
    for model in record.model_calls:
        for message in model["input"]:
            for item in message["content"]:
                if item.get("type") == "function_result":
                    call_id, result = item.get("call_id"), item.get("result")
                    if (
                        message.get("role") != "tool" or not isinstance(call_id, str)
                        or not isinstance(result, str)
                        or (call_id in model_results and model_results[call_id] != result)
                    ):
                        raise ValueError("Malformed/conflicting observed model tool-result history.")
                    model_results[call_id] = result
    final_text: list[str] = []
    observed = iter(record.tool_calls)
    for model in record.model_calls:
        # A completed answer followed by another model call was rejected by self-repair; only the last is scored.
        superseded = model is not record.model_calls[-1] and model.get("finish_reason") == "stop"
        for message in model["output"]:
            if message.get("role") != "assistant" or not message.get("content"):
                raise ValueError("Unexpected model output role or empty content.")
            for item in message["content"]:
                if item.get("type") == "text_reasoning" or (superseded and item.get("type") == "text"):
                    continue
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    response.append({"role": "assistant", "content": [{"type": "text", "text": item["text"]}]})
                    if model is record.model_calls[-1]:
                        final_text.append(item["text"])
                elif item.get("type") == "function_call":
                    name, call_id = item.get("name"), item.get("call_id")
                    args = arguments(item.get("arguments"))
                    if name not in schemas or not isinstance(call_id, str) or not call_id or call_id in seen_ids:
                        raise ValueError("Model tool call lacks a unique observed ID/discovered schema.")
                    seen_ids.add(call_id)
                    from agent_framework import MiddlewareFailure

                    try:
                        require_read(name, args, payload.request, settings)
                        Draft202012Validator(schemas[name]["parameters"]).validate(args)
                    except (MiddlewareFailure, ValidationError, SchemaError) as exc:
                        raise ValueError("Observed tool arguments violate the read policy/schema.") from exc
                    evidence = next(observed, None)
                    server, tool = name.split("___", 1)
                    if (
                        evidence is None or evidence.get("type") != "mcp_call"
                        or evidence.get("status") != "completed" or evidence.get("error")
                        or evidence.get("server_label") != server or evidence.get("name") != tool
                        or arguments(evidence.get("arguments")) != args
                        or not isinstance(evidence.get("output"), str) or not evidence["output"].strip()
                        or model_results.get(call_id) != evidence["output"]
                    ):
                        raise ValueError("Model call and successful observed policy result do not correlate.")
                    call = {"type": "tool_call", "tool_call_id": call_id, "name": name, "arguments": args}
                    calls.append(call)
                    response.extend([
                        {"role": "assistant", "content": [call]},
                        {"role": "tool", "tool_call_id": call_id,
                         "content": [{"type": "tool_result", "tool_result": evidence["output"]}]},
                    ])
                else:
                    raise ValueError("Unsupported or approval/refusal model output; no scorer row produced.")
    if next(observed, None) is not None:
        raise ValueError("Policy result has no corresponding observed model call.")
    if set(model_results) != seen_ids:
        raise ValueError("Model tool-result history does not match the observed calls.")
    if len(final_text) != 1 or record.model_calls[-1]["finish_reason"] != "stop":
        raise ValueError("Evaluation needs one complete observed final model answer.")
    analysis = AnalysisOutput.model_validate_json(final_text[0])
    if assemble_result(payload.request, analysis, report.result.provenance) != report.result:
        raise ValueError("Observed model answer does not assemble to the returned AgentResult.")
    verify_sources(case, {"output": record.tool_calls}, report.result)
    return {
        "case_id": case["id"],
        "query": [{"role": "system", "content": record.instructions},
                  {"role": "user", "content": content["text"]}],
        "response": response,
        "context": json.dumps(
            [call["output"] for call in record.tool_calls] if payload.source_mode == "live_sources"
            else [source.model_dump(mode="json") for source in record.sources]
        ),
        "tool_calls": calls,
        "tool_definitions": list(schemas.values()),
    }


def invoke_evaluation(
    project: Any, case: dict[str, Any], payload: EvaluationRequest, name: str, version: str,
    artifact: HostedArtifact, definition: dict[str, Any], observed_model: str,
    serving_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, lineage = hosted_response(
        project, payload.request, name, version, artifact, evaluation_input=payload.model_dump_json(),
        endpoint_label_version=serving_version,
    )
    report = validate_report(raw, payload, artifact, definition, lineage, observed_model)
    row = evaluator_row(case, payload, report, definition)
    return {**lineage, "evaluation": report.model_dump(mode="json")}, row
