"""Offline P1 acceptance preparation/extraction; no invocation or replacement eval gate."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from contracts.v1 import AgentRequest, AgentResult, AnalysisOutput

CASES = (
    ("order-sync-retry", "assessment-request.json", "change_review"),
    ("order-sync-information-missing", "information-review-request.json", "information_review"),
)


def prepare(repo: Path, output: Path, agent_version: int) -> dict[str, Any]:
    if agent_version < 1:
        raise ValueError("Specify a concrete positive hosted version, never @latest.")
    if output.exists():
        raise ValueError("Use a new output directory; previous acceptance evidence must not be overwritten.")
    dataset = repo / "evals" / "datasets"
    suite = json.loads((dataset / "suite.json").read_text(encoding="utf-8"))
    files: dict[str, str] = {}
    manifest: dict[str, Any] = {
        "state": "prepared_not_run",
        "agent": "documentation-agent",
        "agent_version": agent_version,
        "expected_app_version": "0.4.0",
        "note": "Version is operator-supplied, not verified. No inference or evaluation has run.",
        "cases": [],
    }
    for case_id, example, scope in CASES:
        original_bytes = (dataset / f"{case_id}.json").read_bytes()
        scenario = json.loads(original_bytes)
        matches = [case for case in suite["cases"] if case["id"] == case_id]
        if len(matches) != 1 or matches[0]["input_mode"] != "live_sources":
            raise ValueError(f"Canonical live case {case_id} is missing or ambiguous.")
        canonical = AgentRequest.model_validate(matches[0]["request"])
        sample = AgentRequest.model_validate_json(
            (repo / "src" / "agents" / "documentation-agent" / "examples" / example).read_text(encoding="utf-8")
        )
        if sample.task is None or sample.task.scope != scope or sample.task.question != scenario["prompt"]:
            raise ValueError(f"Example task no longer matches the original {case_id} question.")
        for field in ("subject", "context", "documentation_standard_ref"):
            if getattr(sample, field) != getattr(canonical, field):
                raise ValueError(f"Example {field} differs from the canonical {case_id} input.")
        canonical.task = sample.task
        canonical.request_id = uuid4()
        canonical.correlation_id = uuid4()
        files[f"{case_id}-request.json"] = canonical.model_dump_json()
        manifest["cases"].append(
            {
                "id": case_id,
                "request": f"{case_id}-request.json",
                "request_id": str(canonical.request_id),
                "correlation_id": str(canonical.correlation_id),
                "scenario": f"evals/datasets/{case_id}.json",
                "scenario_sha256": hashlib.sha256(original_bytes).hexdigest(),
                "expected_status": scenario["expected_status"],
            }
        )
    output.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def response_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        events = []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if payload == "[DONE]":
                continue
            event = json.loads(payload)
            if not isinstance(event, dict):
                raise ValueError("Malformed Responses event.") from None
            if event.get("type") in {"response.failed", "response.incomplete", "error"}:
                raise ValueError("Responses stream reports failure/incomplete output.") from None
            if event.get("type") == "response.completed":
                events.append(event.get("response"))
        if len(events) != 1:
            raise ValueError("Expected exactly one response.completed event.") from None
        value = events[0]
    if not isinstance(value, dict):
        raise ValueError("Expected a Responses JSON object.")
    return value


def extract(request: AgentRequest, raw: dict[str, Any], expected_app_version: str) -> AgentResult:
    if raw.get("status") != "completed" or raw.get("error"):
        raise ValueError("Hosted response did not complete successfully.")
    output = raw.get("output")
    if not isinstance(output, list) or len(output) != 1:
        raise ValueError("Expected exactly one hosted assistant message, with no approval/tool output.")
    item = output[0]
    if not isinstance(item, dict) or item.get("type") != "message" or item.get("role") != "assistant":
        raise ValueError("Expected a hosted assistant message.")
    parts = item.get("content", [])
    if (
        not isinstance(parts, list)
        or len(parts) != 1
        or not isinstance(parts[0], dict)
        or parts[0].get("type") != "output_text"
    ):
        raise ValueError("Expected one structured output_text result.")
    result = AgentResult.model_validate_json(parts[0]["text"])
    if result.request_id != request.request_id:
        raise ValueError("Result belongs to another request.")
    if result.provenance.agent_name != "documentation-agent":
        raise ValueError("Unexpected agent provenance.")
    if result.provenance.agent_version != expected_app_version:
        raise ValueError("Unexpected application version; this is not the intended artifact.")
    if request.task is None:
        raise ValueError("Task-aware acceptance requires an explicit task.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--repo-root", type=Path, default=Path.cwd())
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--agent-version", type=int, required=True)
    read = commands.add_parser("extract")
    read.add_argument("--request", type=Path, required=True)
    read.add_argument("--response", type=Path, required=True)
    read.add_argument("--output", type=Path, required=True)
    read.add_argument(
        "--analysis-output", type=Path, required=True, help="Analysis-only input for the existing checker"
    )
    read.add_argument("--expected-app-version", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.repo_root, args.output_dir, args.agent_version)
        print(f"Prepared two requests in {args.output_dir}; not invoked or evaluated.")
    else:
        request = AgentRequest.model_validate_json(args.request.read_text(encoding="utf-8-sig"))
        raw = response_json(args.response.read_text(encoding="utf-8-sig"))
        result = extract(request, raw, args.expected_app_version)
        analysis = AnalysisOutput.model_validate(result.model_dump(include=set(AnalysisOutput.model_fields)))
        if args.output.resolve() == args.analysis_output.resolve():
            raise ValueError("Result and analysis paths must differ.")
        if args.output.exists() or args.analysis_output.exists():
            raise ValueError("Refusing to overwrite previous result or analysis evidence.")
        with args.output.open("x", encoding="utf-8") as file:
            file.write(result.model_dump_json(indent=2))
        with args.analysis_output.open("x", encoding="utf-8") as file:
            file.write(analysis.model_dump_json(indent=2))
        print(f"Extracted correlated result to {args.output}; quality and served version remain unverified.")


if __name__ == "__main__":
    main()
