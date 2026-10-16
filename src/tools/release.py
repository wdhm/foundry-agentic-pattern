"""Manual create-version -> built-in eval gate. Never changes serving traffic."""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.v1 import assemble_result
from tools.cli import analysis_from_response, selected_provenance
from tools.release_sources import evaluator_item, load_cases, verify_sources

METRICS = {"groundedness": (1, 5), "task_adherence": (0, 1), "tool_call_accuracy": (1, 5)}


class ReleasePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_endpoint: str = Field(pattern=r"^https://[^/]+/api/projects/[^/?#]+$")
    agent_name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    base_version: str = Field(pattern=r"^[1-9][0-9]*$")
    serving_version: str = Field(pattern=r"^[1-9][0-9]*$")
    expected_endpoint: dict[str, Any]
    expected_identity: dict[str, Any]
    candidate_definition: dict[str, Any]
    model_version: str = Field(min_length=1)
    eval_model_version: str = Field(min_length=1)
    thresholds: dict[str, float]
    approval_reference: str = Field(min_length=1)
    writer_hold_reference: str = Field(min_length=1)
    evaluator_compatibility_reference: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    expires_at: datetime

    @model_validator(mode="after")
    def reviewed_criteria(self) -> "ReleasePlan":
        if any(
            version.lower() in {"latest", "@latest", "unknown", "current", "none", "null"}
            for version in (self.model_version, self.eval_model_version)
        ):
            raise ValueError("Model versions must be concrete reviewed deployment versions.")
        if set(self.thresholds) != set(METRICS):
            raise ValueError("Explicit release thresholds for all three built-in evaluators are required.")
        for metric, threshold in self.thresholds.items():
            lower, upper = METRICS[metric]
            if not math.isfinite(threshold) or not lower <= threshold <= upper:
                raise ValueError(f"Invalid threshold for {metric}; expected {lower}..{upper}.")
        if not self.expected_identity or not self.expected_endpoint:
            raise ValueError("Reviewed exact serving endpoint and identity snapshots are required.")
        self.check_approval()
        return self

    def check_approval(self) -> None:
        if self.expires_at.tzinfo is None or self.expires_at <= datetime.now(UTC):
            raise ValueError("Release approval/writer hold is missing a future timezone-aware expiry.")


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def require_pin(agent: dict[str, Any], plan: ReleasePlan) -> None:
    if agent["name"] != plan.agent_name:
        raise ValueError("Serving GET returned a different agent.")
    if (
        agent.get("agent_endpoint") != plan.expected_endpoint
        or agent.get("instance_identity") != plan.expected_identity
    ):
        raise ValueError("Serving configuration/identity changed; coordinate writers and review again.")
    rules = agent["agent_endpoint"].get("version_selector", {}).get("version_selection_rules")
    if rules != [{"type": "FixedRatio", "agent_version": plan.serving_version, "traffic_percentage": 100}]:
        raise ValueError("Serving must GET-prove a reviewed concrete version at 100%; @latest is unsafe.")


def gate(items: list[dict[str, Any]], expected_count: int, thresholds: dict[str, float]) -> None:
    if (
        len(items) != expected_count
        or any(type(item.get("datasource_item_id")) is not int for item in items)
        or {item["datasource_item_id"] for item in items} != set(range(expected_count))
    ):
        raise ValueError("Incomplete, duplicated or unknown evaluation rows.")
    for item in items:
        if item.get("status") != "completed" or item.get("error") or (item.get("sample") or {}).get("error"):
            raise ValueError("Evaluation row failed, skipped or did not complete.")
        results = item.get("results", [])
        if len(results) != len(thresholds) or {result.get("name") for result in results} != set(thresholds):
            raise ValueError("Missing, duplicated or unexpected built-in evaluator results.")
        for result in results:
            score = result.get("score")
            lower, upper = METRICS[result["name"]]
            if (
                result.get("type") != "azure_ai_evaluator"
                or result.get("passed") is not True
                or ("label" in result and result["label"] != "pass")
                or result.get("error")
                or result.get("status", "completed") != "completed"
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or not lower <= score <= upper
                or score < thresholds[result["name"]]
            ):
                raise ValueError(f"Blocking built-in evaluation: {result['name']}.")


class FoundryRelease:
    def __init__(self, project: Any, client: Any) -> None:
        self.project = project
        self.client = client

    def agent(self, name: str) -> dict[str, Any]:
        return dict(self.project.agents.get(name).as_dict())

    def version(self, name: str, version: str) -> dict[str, Any]:
        return dict(self.project.agents.get_version(name, version).as_dict())

    def model_version(self, deployment: str) -> str:
        version = self.project.deployments.get(deployment).model_version
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Deployment GET did not return a model version.")
        return version

    def create(self, plan: ReleasePlan, metadata: dict[str, str]) -> dict[str, Any]:
        from azure.ai.projects.models import PromptAgentDefinition

        return dict(
            self.project.agents.create_version(
                agent_name=plan.agent_name,
                definition=PromptAgentDefinition(plan.candidate_definition),
                metadata=metadata,
            ).as_dict()
        )

    def respond(self, case: dict[str, Any], name: str, version: str) -> dict[str, Any]:
        options = {"tool_choice": "none"} if case["mode"] == "supplied_sources" else {}
        return dict(
            self.client.responses.create(
                input=case["input"],
                metadata={
                    "request_id": str(case["request"].request_id),
                    "correlation_id": str(case["request"].correlation_id),
                },
                extra_body={"agent_reference": {"type": "agent_reference", "name": name, "version": version}},
                **options,
            ).model_dump()
        )

    def evaluate(
        self, rows: list[dict[str, Any]], thresholds: dict[str, float], deployment: str, output: Path, group: str
    ) -> list[dict[str, Any]]:
        from azure.ai.projects.models import TestingCriterionAzureAIEvaluator

        criteria = []
        for metric, threshold in thresholds.items():
            fields = ["query", "response"]
            if metric == "groundedness":
                fields.append("context")
            if metric in {"task_adherence", "tool_call_accuracy"}:
                fields.append("tool_definitions")
            if metric == "tool_call_accuracy":
                fields.append("tool_calls")
            criteria.append(
                TestingCriterionAzureAIEvaluator(
                    type="azure_ai_evaluator",
                    name=metric,
                    evaluator_name="builtin." + metric,
                    initialization_parameters={"deployment_name": deployment, "threshold": threshold},
                    data_mapping={field: "{{item." + field + "}}" for field in fields},
                )
            )
        schema = {
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "query": {"type": "array", "items": {"type": "object"}},
                "response": {"type": "array", "items": {"type": "object"}},
                "context": {"type": "string"},
                "tool_calls": {"type": "array", "items": {"type": "object"}},
                "tool_definitions": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["case_id", "query", "response", "context", "tool_calls", "tool_definitions"],
        }
        evaluation = self.client.evals.create(
            name="documentation-release-" + group,
            data_source_config={"type": "custom", "item_schema": schema},
            testing_criteria=criteria,
        )
        save(output / f"{group}-evaluation.json", evaluation.model_dump())
        run = self.client.evals.runs.create(
            eval_id=evaluation.id,
            name="documentation-release-" + group,
            data_source={
                "type": "jsonl",
                "source": {
                    "type": "file_content",
                    "content": [{"item": row} for row in rows],
                },
            },
        )
        save(output / f"{group}-run.json", run.model_dump())
        deadline = time.monotonic() + 1200
        while run.status in {"queued", "in_progress"} and time.monotonic() < deadline:
            time.sleep(5)
            run = self.client.evals.runs.retrieve(eval_id=evaluation.id, run_id=run.id)
            save(output / f"{group}-run.json", run.model_dump())
        if run.status != "completed" or run.error:
            raise ValueError(f"Evaluation ended without success: {run.status}; run {run.id}.")
        items = [
            item.model_dump() for item in self.client.evals.runs.output_items.list(eval_id=evaluation.id, run_id=run.id)
        ]
        save(output / f"{group}-scores.json", items)
        return items


def execute(
    cloud: FoundryRelease,
    plan: ReleasePlan,
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
    deployment: str,
    output: Path,
) -> None:
    if not deployment.strip():
        raise ValueError("EVAL_MODEL_DEPLOYMENT is required; no model is selected or provisioned automatically.")
    plan.check_approval()
    before = cloud.agent(plan.agent_name)
    require_pin(before, plan)
    save(
        output / "serving-before.json",
        {
            "name": before["name"],
            "agent_endpoint": before["agent_endpoint"],
            "instance_identity": before["instance_identity"],
        },
    )
    serving = cloud.version(plan.agent_name, plan.serving_version)
    base = cloud.version(plan.agent_name, plan.base_version)
    for version, expected in ((serving, plan.serving_version), (base, plan.base_version)):
        if version["name"] != plan.agent_name or version["version"] != expected or version["status"] != "active":
            raise ValueError("Reviewed serving/base version is not active or does not match.")
    if before["versions"]["latest"]["version"] != plan.base_version:
        raise ValueError("Base version is no longer latest; review intervening changes.")
    definition = plan.candidate_definition
    if {k: v for k, v in definition.items() if k != "instructions"} != {
        k: v for k, v in base["definition"].items() if k != "instructions"
    }:
        raise ValueError(
            "This release path only changes instructions; tools/model/schema/policy metadata stay inherited."
        )
    if not definition.get("instructions", "").strip():
        raise ValueError("Candidate instructions are empty.")
    if not definition["instructions"].startswith(base["definition"]["instructions"]):
        raise ValueError("The MVP candidate must retain all base instructions/policy verbatim; append-only changes.")
    metadata = base.get("metadata") or {}
    selected_provenance(plan.agent_name, plan.base_version, definition, metadata, plan.model_version)
    if cloud.model_version(definition["model"]) != plan.model_version:
        raise ValueError("Agent model deployment version differs from reviewed provenance.")
    if cloud.model_version(deployment) != plan.eval_model_version:
        raise ValueError("Evaluator model deployment version differs from reviewed compatibility evidence.")
    plan.check_approval()
    rechecked = cloud.agent(plan.agent_name)
    require_pin(rechecked, plan)
    if rechecked["versions"]["latest"]["version"] != plan.base_version:
        raise ValueError("Another writer created a version during preflight; stop and renew coordination.")
    created = cloud.create(plan, metadata)
    version = created["version"]
    save(
        output / "candidate.json",
        {
            "name": created["name"],
            "version": version,
            "dataset_version": suite["dataset_version"],
            "suite_sha256": hashlib.sha256(json.dumps(suite, sort_keys=True).encode()).hexdigest(),
            "definition_sha256": hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest(),
            "approval_reference": plan.approval_reference,
            "writer_hold_reference": plan.writer_hold_reference,
            "evaluator_compatibility_reference": plan.evaluator_compatibility_reference,
        },
    )
    if created["name"] != plan.agent_name or not re.fullmatch(r"[1-9][0-9]*", version) or version == plan.base_version:
        raise ValueError("Create returned an invalid candidate identity.")
    candidate = cloud.version(plan.agent_name, version)
    if (
        candidate["name"] != plan.agent_name
        or candidate["version"] != version
        or candidate["status"] != "active"
        or candidate["definition"] != definition
        or candidate.get("metadata") != metadata
    ):
        raise ValueError("Candidate readback is not active or differs from reviewed definition/metadata.")
    provenance = selected_provenance(plan.agent_name, version, definition, metadata, plan.model_version)
    rows: dict[str, list[dict[str, Any]]] = {"live_sources": [], "supplied_sources": []}
    response_ids: set[str] = set()
    for case in cases:
        plan.check_approval()
        require_pin(cloud.agent(plan.agent_name), plan)
        raw = cloud.respond(case, plan.agent_name, version)
        save(output / (case["id"] + "-response.json"), raw)
        if not raw.get("id") or raw["id"] in response_ids:
            raise ValueError("A unique response ID is required for truthful run lineage.")
        response_ids.add(raw["id"])
        result = assemble_result(case["request"], analysis_from_response(raw), provenance)
        verify_sources(case, raw, result)
        save(
            output / (case["id"] + "-result.json"),
            {
                "run_id": raw["id"],
                "correlation_id": str(case["request"].correlation_id),
                "input_mode": case["mode"],
                "result": result.model_dump(mode="json"),
            },
        )
        rows[case["mode"]].append(evaluator_item(case, raw, result, definition["instructions"]))
    for mode, group in rows.items():
        plan.check_approval()
        require_pin(cloud.agent(plan.agent_name), plan)
        thresholds = {k: v for k, v in plan.thresholds.items() if k != "tool_call_accuracy" or mode == "live_sources"}
        if len(group) != (2 if mode == "live_sources" else 3):
            raise ValueError("Incomplete case group; release blocked.")
        save(output / f"{mode}-inputs.json", group)
        scored = cloud.evaluate(group, thresholds, deployment, output, mode)
        gate(scored, len(group), thresholds)
    plan.check_approval()
    after = cloud.agent(plan.agent_name)
    require_pin(after, plan)
    save(
        output / "serving-after.json",
        {
            "name": after["name"],
            "agent_endpoint": after["agent_endpoint"],
            "instance_identity": after["instance_identity"],
        },
    )
    if (
        cloud.model_version(definition["model"]) != plan.model_version
        or cloud.model_version(deployment) != plan.eval_model_version
    ):
        raise ValueError("A model deployment version changed during evaluation; results cannot certify this candidate.")
    save(
        output / "decision.json",
        {
            "status": "eligible_for_manual_review",
            "promoted": False,
            "candidate_version": version,
            "serving_version": plan.serving_version,
            "thresholds": plan.thresholds,
            "dataset_version": suite["dataset_version"],
            "tool_call_accuracy_scope": "two live-source cases only; not applicable to three tools-disabled cases",
            "baseline_comparison": "not performed; no built-in baseline supplied",
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--suite", type=Path, default=Path("evals/datasets/suite.json"))
    parser.add_argument("--execute-approved-cloud", action="store_true")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / "decision.json", {"status": "blocked", "promoted": False})
    try:
        plan = ReleasePlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
        suite, cases = load_cases(args.suite, Path.cwd())
        deployment = os.environ.get("EVAL_MODEL_DEPLOYMENT", "")
        if not deployment.strip():
            raise ValueError("EVAL_MODEL_DEPLOYMENT must be explicitly configured.")
        if not args.execute_approved_cloud:
            raise ValueError("Cloud execution requires separate approval and --execute-approved-cloud.")
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=plan.project_endpoint, credential=credential) as project,
            project.get_openai_client() as client,
        ):
            execute(FoundryRelease(project, client), plan, suite, cases, deployment, args.output)
        return 0
    except (ValueError, OSError, ImportError) as exc:
        save(args.output / "decision.json", {"status": "blocked", "promoted": False, "error": str(exc)})
        print(f"documentation-release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
