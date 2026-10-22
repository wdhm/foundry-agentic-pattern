"""Score the five assessment cases from saved hosted captures, without network or judges."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contracts.evaluation import EvaluationResponse
from tools.hosted import HostedArtifact, validate_hosted_definition
from tools.hosted_evaluation import evaluation_request, evaluator_row, validate_execution
from tools.hosted_release import HostedEvaluationConfig
from tools.release_sources import load_cases, verify_sources

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ("contract_valid", "status_matches", "source_consistent", "execution_valid")
# Existing adapters consume untyped SDK/tool dictionaries. Malformed saved input is a failed
# case, not a reason to stop scoring the remaining required cases.
INPUT_ERRORS = (ValueError, KeyError, TypeError, IndexError, AttributeError)


class ReplayPlan(BaseModel):
    """Only immutable scoring inputs; expired write approvals are not renewed by replay."""

    model_config = ConfigDict(extra="ignore")
    artifact: HostedArtifact
    candidate_definition: dict[str, Any]
    evaluation: HostedEvaluationConfig
    project_endpoint: str
    model_version: str
    serving_version: str = Field(pattern=r"^[1-9][0-9]*$")


class Capture(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: str = Field(min_length=1)
    response_ids: list[str] = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    agent_version: str = Field(pattern=r"^[1-9][0-9]*$")
    agent_session_id: str = Field(min_length=1)
    session_version_indicator: dict[str, str]
    outer_agent_reference: dict[str, str]
    version_evidence: str
    image: str
    source_commit: str
    build_reference: str
    request_id: UUID
    correlation_id: UUID
    evaluation: EvaluationResponse


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_json(path: Path) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}.")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON number: {value}.")

    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs, parse_constant=invalid_constant,
    )


def validate_lineage(capture: Capture, plan: ReplayPlan) -> None:
    artifact = plan.artifact
    version = capture.agent_version
    outer = capture.outer_agent_reference
    if (
        capture.agent_name != artifact.runtime_provenance.agent_name
        or capture.session_version_indicator != {"type": "version_ref", "agent_version": version}
        or outer.get("type") != "agent_reference" or outer.get("name") != capture.agent_name
        or outer.get("version") not in {version, plan.serving_version}
        or capture.version_evidence != (
            "session_get_and_matching_outer_reference" if outer.get("version") == version
            else "session_get_and_endpoint_serving_label"
        )
        or capture.response_ids != [capture.run_id]
        or (capture.image, capture.source_commit, capture.build_reference)
        != (artifact.image, artifact.source_commit, artifact.build_reference)
    ):
        raise ValueError("Saved outer/session/artifact lineage is missing or inconsistent.")


def score_case(
    case: dict[str, Any], raw: Any, plan: ReplayPlan, *, error: str | None = None,
) -> dict[str, Any]:
    score: dict[str, Any] = {"case_id": case["id"], **dict.fromkeys(CHECKS, False), "passed": False, "error": error}
    row: dict[str, Any] = {"score": score, "result": None}
    try:
        report = EvaluationResponse.model_validate(raw["evaluation"])
    except INPUT_ERRORS as exc:
        score["error"] = error or f"{type(exc).__name__}: {exc}"
        return row
    score["contract_valid"] = True
    row["result"] = raw
    score["status_matches"] = report.result.documentation_status == case["expected_status"]
    problems = [error] if error else []
    if not score["status_matches"]:
        problems.append("Documentation status does not match the unchanged case expectation.")
    # Separate the status verdict from the existing combined source/status validator.
    source_case = {**case, "expected_status": report.result.documentation_status}
    try:
        verify_sources(source_case, {"output": report.execution.tool_calls}, report.result)
        score["source_consistent"] = True
    except INPUT_ERRORS as exc:
        problems.append(f"source_consistent: {type(exc).__name__}: {exc}")
    try:
        capture = Capture.model_validate(raw)
        validate_lineage(capture, plan)
        request = case["request"].model_copy(update={
            "request_id": capture.request_id, "correlation_id": capture.correlation_id,
        })
        payload = evaluation_request({**case, "request": request}, plan.evaluation.task_scopes[case["id"]])
        validate_execution(
            report, payload, plan.artifact, plan.candidate_definition, raw, plan.evaluation.observed_model,
        )
        evaluator_row(source_case, payload, report, plan.candidate_definition)
        score["execution_valid"] = error is None
    except INPUT_ERRORS as exc:
        problems.append(f"execution_valid: {type(exc).__name__}: {exc}")
    score["passed"] = all(score[key] for key in CHECKS) and not problems
    score["error"] = "; ".join(problems) or None
    return row


def evaluate(
    captures: Path, plan_path: Path, suite_path: Path, evidence_kind: Literal["saved_capture", "synthetic"],
) -> list[dict[str, Any]]:
    plan_raw = read_json(plan_path)
    plan = ReplayPlan.model_validate(plan_raw)
    validate_hosted_definition(
        plan.candidate_definition, plan.artifact, plan.project_endpoint, plan.model_version, evaluation=True,
    )
    read_json(suite_path)
    suite, cases = load_cases(suite_path, ROOT)
    if set(plan.evaluation.task_scopes) != {case["id"] for case in cases}:
        raise ValueError("Reviewed task scopes must cover every suite case exactly.")
    if not captures.is_dir():
        raise ValueError("Capture directory does not exist.")
    expected = {case["id"] for case in cases}
    paths = {path.name.removesuffix("-evaluation.json"): path for path in captures.glob("*-evaluation.json")}
    if set(paths) - expected:
        raise ValueError(f"Unexpected case captures: {sorted(set(paths) - expected)}.")
    records: dict[str, Any] = {}
    errors: dict[str, str] = {}
    identities: dict[tuple[str, str], str] = {}
    for case in cases:
        case_id = case["id"]
        try:
            if case_id not in paths:
                raise ValueError("Missing required case capture.")
            raw = read_json(paths[case_id])
            records[case_id] = raw
            capture = Capture.model_validate(raw)
            keys = [
                ("run_id", capture.run_id), ("session_id", capture.agent_session_id),
                ("execution_id", str(capture.evaluation.execution.execution_id)),
                ("request_id", str(capture.request_id)), ("correlation_id", str(capture.correlation_id)),
                *(("model_response_id", call["response_id"]) for call in capture.evaluation.execution.model_calls),
            ]
            for kind, value in keys:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Invalid {kind}.")
                key = (kind, value)
                if key in identities:
                    other = identities[key]
                    message = f"Duplicate {kind} in case captures: {other}, {case_id}."
                    errors[other] = message
                    errors[case_id] = message
                identities[key] = case_id
        except (OSError, *INPUT_ERRORS) as exc:
            errors[case_id] = f"{type(exc).__name__}: {exc}"
    rows = []
    for case in cases:
        row = score_case(case, records.get(case["id"]), plan, error=errors.get(case["id"]))
        row["score"].update({
            "evidence_kind": evidence_kind, "suite_sha256": digest(suite), "plan_sha256": digest(plan_raw),
        })
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True, help="Directory containing CASE_ID-evaluation.json")
    parser.add_argument("--plan", type=Path, required=True, help="Saved hosted evaluation plan (read-only)")
    parser.add_argument("--suite", type=Path, default=ROOT / "evals" / "datasets" / "suite.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "results" / "baseline.json")
    parser.add_argument("--evidence-kind", choices=("saved_capture", "synthetic"), default="saved_capture")
    args = parser.parse_args(argv)
    try:
        # Never overwrite captured inputs or the reviewed plan/suite, even if output is misconfigured.
        inputs = [args.plan, args.suite, *args.captures.glob("*-evaluation.json")]
        if args.output.resolve() in {path.resolve() for path in inputs}:
            raise ValueError("Output must not overwrite an input file.")
        rows = evaluate(args.captures, args.plan, args.suite, args.evidence_kind)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, *INPUT_ERRORS) as exc:
        print(f"Code evaluation input/output error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    passed = sum(row["score"]["passed"] for row in rows)
    print(f"{passed}/{len(rows)} cases passed ({args.evidence_kind}); report: {args.output}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
