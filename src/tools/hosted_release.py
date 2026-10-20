"""Guarded opt-in hosted evaluation release; no routing or approval writes."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tools.hosted import HostedArtifact, validate_hosted_definition
from tools.hosted_evaluation import evaluation_request, invoke_evaluation
from tools.release import FoundryEvaluation, ReleasePlan, gate, require_pin, save
from tools.release_sources import load_cases


class ServingPathProof(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agent_name: str = Field(min_length=1)
    version: str = Field(pattern=r"^[1-9][0-9]*$")
    agent_session_id: str = Field(min_length=1)
    response_id: str = Field(min_length=1)
    selection: Literal["fresh_named_endpoint_session_without_version_override"]
    observed_at: datetime
    evidence_reference: str = Field(min_length=1)


class HostedEvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    isolation_review_reference: str = Field(min_length=1)
    evaluator_deployment: str = Field(min_length=1)
    observed_model: str = Field(min_length=1)
    task_scopes: dict[str, Literal["change_review", "information_review"]]


class HostedReleasePlan(ReleasePlan):
    artifact: HostedArtifact
    serving_path_proof: ServingPathProof
    evaluation: HostedEvaluationConfig | None = None

    @model_validator(mode="after")
    def hosted_criteria(self) -> "HostedReleasePlan":
        if self.agent_name != self.artifact.runtime_provenance.agent_name:
            raise ValueError("Hosted release name must match P1's runtime name.")
        validate_hosted_definition(
            self.candidate_definition, self.artifact, self.project_endpoint, self.model_version,
            evaluation=self.evaluation is not None,
        )
        proof = self.serving_path_proof
        if proof.agent_name != self.agent_name or proof.version != self.serving_version:
            raise ValueError("Serving-path proof must belong to this hosted agent and retained serving version.")
        if (
            proof.observed_at.tzinfo is None
            or proof.observed_at > datetime.now(UTC)
            or (datetime.now(UTC) - proof.observed_at).total_seconds() > 3600
        ):
            raise ValueError("A fresh, timezone-aware serving-path proof within the last hour is required.")
        return self


class FoundryHostedRelease(FoundryEvaluation):
    def create(self, plan: ReleasePlan, metadata: dict[str, str]) -> dict[str, Any]:
        from azure.ai.projects.models import HostedAgentDefinition

        return dict(
            self.project.agents.create_version(
                agent_name=plan.agent_name,
                definition=HostedAgentDefinition(plan.candidate_definition),
                metadata=metadata,
            ).as_dict()
        )

    def await_candidate(self, plan: HostedReleasePlan, version: str, output: Path) -> dict[str, Any]:
        deadline = time.monotonic() + 600
        while True:
            plan.check_approval()
            require_pin(self.agent(plan.agent_name), plan)
            candidate = self.version(plan.agent_name, version)
            save(output / "candidate-readback.json", candidate)
            if candidate.get("name") != plan.agent_name or candidate.get("version") != version:
                raise ValueError("Hosted candidate readback returned another name/version.")
            if candidate.get("status") == "active":
                return candidate
            if candidate.get("status") != "creating" or time.monotonic() >= deadline:
                raise ValueError(f"Hosted candidate readiness failed or timed out: {candidate.get('status')!r}.")
            time.sleep(5)


def prepare_candidate(cloud: FoundryHostedRelease, plan: HostedReleasePlan, deployment: str, output: Path) -> str:
    """Create only under a retained concrete serving pin and reviewed writer hold."""
    if not deployment.strip():
        raise ValueError("EVAL_MODEL_DEPLOYMENT is required.")
    # Revalidate mutable plans, proof freshness and approval at execution time.
    plan = HostedReleasePlan.model_validate(plan.model_dump())
    if plan.evaluation is not None and deployment != plan.evaluation.evaluator_deployment:
        raise ValueError("Evaluator deployment differs from the reviewed evaluation configuration.")
    before = cloud.agent(plan.agent_name)
    require_pin(before, plan)
    save(output / "serving-before.json", before)
    if before["versions"]["latest"]["version"] != plan.base_version:
        raise ValueError("Hosted base is no longer latest; renew review and writer coordination.")
    base = cloud.version(plan.agent_name, plan.base_version)
    serving = cloud.version(plan.agent_name, plan.serving_version)
    for version, expected in ((base, plan.base_version), (serving, plan.serving_version)):
        if version["name"] != plan.agent_name or version["version"] != expected or version["status"] != "active":
            raise ValueError("Hosted base/serving version must match and be active.")
        if version["definition"].get("kind") != "hosted":
            raise ValueError("A hosted release cannot inherit a prompt-agent version.")
    if (
        serving["definition"].get("environment_variables", {}).get("DOCUMENTATION_MODE") != "assessment"
        or serving["definition"].get("environment_variables", {}).get("DOCUMENTATION_ENABLE_EVALUATION") == "true"
    ):
        raise ValueError("Serving must remain ordinary assessment, never the source-bearing evaluation interface.")
    retained = {
        key: value for key, value in base["definition"].items()
        if key not in {"container_configuration", "environment_variables"}
    }
    candidate_retained = {
        key: value for key, value in plan.candidate_definition.items()
        if key not in {"container_configuration", "environment_variables"}
    }
    if retained != candidate_retained:
        raise ValueError("Hosted release must preserve protocols, resources, telemetry and other non-image settings.")
    if {
        key: value for key, value in base["definition"].get("container_configuration", {}).items() if key != "image"
    } != {
        key: value for key, value in plan.candidate_definition["container_configuration"].items() if key != "image"
    }:
        raise ValueError("Hosted registry connection/auth settings must stay inherited.")
    runtime_keys = {
        "DOCUMENTATION_MODE", "DOCUMENTATION_AUTH_MODE", "DOCUMENTATION_PROJECT_ENDPOINT",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME", "DOCUMENTATION_MODEL_VERSION", "TOOLBOX_ENDPOINT",
        "DOCUMENTATION_ADO_PROJECT", "DOCUMENTATION_ADO_WIKI", "HOST", "PORT",
    }
    if plan.evaluation is not None:
        runtime_keys.add("DOCUMENTATION_ENABLE_EVALUATION")
    if {
        key: value for key, value in base["definition"].get("environment_variables", {}).items()
        if key not in runtime_keys
    } != {
        key: value for key, value in plan.candidate_definition["environment_variables"].items()
        if key not in runtime_keys
    }:
        raise ValueError("Hosted non-runtime environment settings must stay inherited.")
    metadata = base.get("metadata") or {}
    model = plan.artifact.runtime_provenance.model
    if cloud.model_version(model) != plan.model_version or cloud.model_version(deployment) != plan.eval_model_version:
        raise ValueError("Hosted/evaluator model version differs from reviewed deployment evidence.")
    plan.check_approval()
    rechecked = cloud.agent(plan.agent_name)
    require_pin(rechecked, plan)
    if rechecked["versions"]["latest"]["version"] != plan.base_version:
        raise ValueError("Another writer created a hosted version during preflight.")
    created = cloud.create(plan, metadata)
    save(
        output / "candidate.json",
        {
            "name": created["name"],
            "version": created["version"],
            "artifact": plan.artifact.model_dump(mode="json"),
            "approval_reference": plan.approval_reference,
            "writer_hold_reference": plan.writer_hold_reference,
            "serving_path_proof": plan.serving_path_proof.model_dump(mode="json"),
            "promoted": False,
        },
    )
    version = created["version"]
    if (
        created["name"] != plan.agent_name
        or not isinstance(version, str)
        or not re.fullmatch(r"[1-9][0-9]*", version)
        or version in {plan.base_version, plan.serving_version}
    ):
        raise ValueError("Hosted create returned an invalid candidate identity.")
    candidate = cloud.await_candidate(plan, version, output)
    if candidate["definition"] != plan.candidate_definition or (candidate.get("metadata") or {}) != metadata:
        raise ValueError("Hosted candidate definition/metadata differs from reviewed immutable inputs.")
    require_pin(cloud.agent(plan.agent_name), plan)
    return version


def preflight(plan: HostedReleasePlan, cases: list[dict[str, Any]], deployment: str) -> list[str]:
    blockers = []
    if sum(case["mode"] == "live_sources" for case in cases) != 2 or len(cases) != 5:
        blockers.append("The unchanged suite requires two live-source and three supplied-source cases.")
    if plan.evaluation is None:
        blockers.append(
            "Full hosted gate requires reviewed evaluation config and an explicitly opted-in isolated "
            "evaluation candidate; ordinary assessment remains bare AgentRequest."
        )
    else:
        if set(plan.evaluation.task_scopes) != {case["id"] for case in cases}:
            blockers.append("Review explicit task scopes for every unchanged suite case, without gold/label input.")
        if deployment != plan.evaluation.evaluator_deployment:
            blockers.append("EVAL_MODEL_DEPLOYMENT differs from the explicitly reviewed evaluator deployment.")
        if not blockers:
            for case in cases:
                evaluation_request(case, plan.evaluation.task_scopes[case["id"]])
    if not deployment.strip():
        blockers.append("EVAL_MODEL_DEPLOYMENT must be explicitly configured and compatibility-reviewed.")
    return blockers


def execute(
    cloud: FoundryHostedRelease, plan: HostedReleasePlan, suite: dict[str, Any],
    cases: list[dict[str, Any]], deployment: str, output: Path,
) -> None:
    plan = HostedReleasePlan.model_validate(plan.model_dump())
    blockers = preflight(plan, cases, deployment)
    if blockers:
        raise ValueError("Hosted preflight blocked: " + "; ".join(blockers))
    config = plan.evaluation
    if config is None:
        raise ValueError("Reviewed isolated evaluation configuration is required.")
    save(output / "evaluation-manifest.json", {
        "dataset_version": suite["dataset_version"],
        "suite_sha256": hashlib.sha256(json.dumps(suite, sort_keys=True).encode()).hexdigest(),
        "definition_sha256": hashlib.sha256(json.dumps(plan.candidate_definition, sort_keys=True).encode()).hexdigest(),
        "evaluation_config": config.model_dump(mode="json"),
        "evaluator_model_version": plan.eval_model_version,
        "evaluator_compatibility_reference": plan.evaluator_compatibility_reference,
        "approval_reference": plan.approval_reference, "writer_hold_reference": plan.writer_hold_reference,
    })
    version = prepare_candidate(cloud, plan, deployment, output)
    groups: dict[str, list[dict[str, Any]]] = {"live_sources": [], "supplied_sources": []}
    identities: dict[str, set[str]] = {
        key: set() for key in ("run_id", "agent_session_id", "execution_id", "model_response_id")
    }
    for case in cases:
        plan.check_approval()
        require_pin(cloud.agent(plan.agent_name), plan)
        payload = evaluation_request(case, config.task_scopes[case["id"]])
        report, row = invoke_evaluation(
            cloud.project, case, payload, plan.agent_name, version, plan.artifact,
            plan.candidate_definition, config.observed_model,
        )
        save(output / (case["id"] + "-evaluation.json"), report)
        actual = {
            "run_id": report["run_id"], "agent_session_id": report["agent_session_id"],
            "execution_id": report["evaluation"]["execution"]["execution_id"],
        }
        for key, value in actual.items():
            if value in identities[key]:
                raise ValueError(f"Repeated hosted {key}; evaluation lineage is not independent.")
            identities[key].add(value)
        for call in report["evaluation"]["execution"]["model_calls"]:
            if call["response_id"] in identities["model_response_id"]:
                raise ValueError("Repeated model response ID across hosted case executions.")
            identities["model_response_id"].add(call["response_id"])
        groups[case["mode"]].append(row)
    for mode, rows in groups.items():
        plan.check_approval()
        require_pin(cloud.agent(plan.agent_name), plan)
        if len(rows) != (2 if mode == "live_sources" else 3):
            raise ValueError("Incomplete unchanged five-case group.")
        thresholds = {key: value for key, value in plan.thresholds.items()
                      if key != "tool_call_accuracy" or mode == "live_sources"}
        save(output / (mode + "-inputs.json"), rows)
        gate(cloud.evaluate(rows, thresholds, deployment, output, mode), len(rows), thresholds)
    plan.check_approval()
    after = cloud.agent(plan.agent_name)
    require_pin(after, plan)
    save(output / "serving-after.json", after)
    if (
        cloud.model_version(plan.artifact.runtime_provenance.model) != plan.model_version
        or cloud.model_version(deployment) != plan.eval_model_version
    ):
        raise ValueError("Hosted/evaluator model version changed during evaluation.")
    save(output / "decision.json", {
        "status": "eligible_for_manual_review", "promoted": False, "target": "hosted",
        "candidate_purpose": "isolated_evaluation_only", "promotion_eligible": False,
        "review_scope": "evaluation evidence; rollout requires ordinary assessment config and separate review",
        "candidate_version": version, "serving_version": plan.serving_version,
        "dataset_version": suite["dataset_version"], "thresholds": plan.thresholds,
        "evaluation_config": config.model_dump(mode="json"),
        "tool_call_accuracy_scope": "two observed live cases only; not applicable to three tools-disabled cases",
        "version_evidence": "GET-confirmed session and matching outer reference; not serving-path proof",
        "baseline_comparison": "not performed; no built-in baseline supplied",
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=Path("evals/datasets/suite.json"))
    parser.add_argument("--execute-approved-cloud", action="store_true")
    parser.add_argument("--preflight-only", action="store_true", help="Local validation only; never credentials/cloud.")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    decision: dict[str, Any] = {"status": "blocked", "promoted": False, "target": "hosted"}
    save(args.output / "decision.json", decision)
    try:
        plan = HostedReleasePlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
        suite, cases = load_cases(args.suite, Path.cwd())
        deployment = os.environ.get("EVAL_MODEL_DEPLOYMENT", "").strip()
        blockers = preflight(plan, cases, deployment)
        if not args.preflight_only and not args.execute_approved_cloud:
            blockers.append("Cloud execution requires separate approval and --execute-approved-cloud.")
        decision.update(
            dataset_version=suite["dataset_version"],
            artifact=plan.artifact.model_dump(mode="json"),
            blockers=blockers,
        )
        save(args.output / "decision.json", decision)
        if blockers:
            raise ValueError("Hosted release blocked: " + "; ".join(blockers))
        if args.preflight_only:
            decision.update(status="local_preflight_passed", cloud_readiness="not_checked")
            save(args.output / "decision.json", decision)
            return 0
        from azure.ai.projects import AIProjectClient
        from azure.core.exceptions import AzureError
        from azure.identity import DefaultAzureCredential
        from openai import OpenAIError

        try:
            with (
                DefaultAzureCredential() as credential,
                AIProjectClient(endpoint=plan.project_endpoint, credential=credential) as project,
                project.get_openai_client() as client,
            ):
                execute(FoundryHostedRelease(project, client), plan, suite, cases, deployment, args.output)
        except (AzureError, OpenAIError) as exc:
            raise ValueError(f"Hosted/evaluator SDK operation failed: {type(exc).__name__}: {exc}") from exc
        return 0
    except (ValueError, OSError, ImportError) as exc:
        decision["error"] = str(exc)
        save(args.output / "decision.json", decision)
        print(f"documentation-release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
