"""Hosted release preflight and version primitives; current P1 suite gaps fail closed."""

import argparse
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tools.hosted import HostedArtifact, suite_blockers, validate_hosted_definition
from tools.release import FoundryProject, ReleasePlan, require_pin, save
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


class HostedReleasePlan(ReleasePlan):
    artifact: HostedArtifact
    serving_path_proof: ServingPathProof

    @model_validator(mode="after")
    def hosted_criteria(self) -> "HostedReleasePlan":
        if self.agent_name != self.artifact.runtime_provenance.agent_name:
            raise ValueError("Hosted release name must match P1's runtime name.")
        validate_hosted_definition(
            self.candidate_definition, self.artifact, self.project_endpoint, self.model_version
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


class FoundryHostedRelease(FoundryProject):
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
    """Reviewed primitive; CLI deliberately blocks before this until the full suite is supported."""
    if not deployment.strip():
        raise ValueError("EVAL_MODEL_DEPLOYMENT is required.")
    # Revalidate mutable plans, proof freshness and approval at execution time.
    plan = HostedReleasePlan.model_validate(plan.model_dump())
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=Path("evals/datasets/suite.json"))
    parser.add_argument("--execute-approved-cloud", action="store_true")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    decision: dict[str, Any] = {"status": "blocked", "promoted": False, "target": "hosted"}
    save(args.output / "decision.json", decision)
    try:
        plan = HostedReleasePlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
        suite, cases = load_cases(args.suite, Path.cwd())
        blockers = suite_blockers(cases)
        if not os.environ.get("EVAL_MODEL_DEPLOYMENT", "").strip():
            blockers.append("EVAL_MODEL_DEPLOYMENT must be explicitly configured and compatibility-reviewed.")
        if not args.execute_approved_cloud:
            blockers.append("Cloud execution requires separate approval and --execute-approved-cloud.")
        decision.update(
            dataset_version=suite["dataset_version"],
            artifact=plan.artifact.model_dump(mode="json"),
            blockers=blockers,
        )
        save(args.output / "decision.json", decision)
        # No SDK credentials, version creation or evaluation when P1 cannot honor the suite.
        raise ValueError("Hosted release blocked: " + "; ".join(blockers))
    except (ValueError, OSError, ImportError) as exc:
        decision["error"] = str(exc)
        save(args.output / "decision.json", decision)
        print(f"documentation-release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
