"""Hosted assessment transport and reviewed artifact checks; no routing writes."""

import json
import re
import sys
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.v1 import AgentRequest, AgentResult, Provenance
from tools.cli import structured_text


class HostedArtifact(BaseModel):
    """Operator-reviewed association of a registry digest, build and P1 provenance."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    image: str = Field(pattern=r"^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    build_reference: str = Field(min_length=1)
    readiness_review_reference: str = Field(min_length=1)
    runtime_provenance: Provenance


def assessment_provenance(definition: dict[str, Any]) -> Provenance:
    # Use P1's settings and instruction/policy assembly, never a second contract.
    from documentation_agent.assessment import AssessmentAgent
    from documentation_agent.settings import AssessmentSettings

    environment = definition.get("environment_variables", {})
    if environment.get("DOCUMENTATION_MODE") != "assessment":
        raise ValueError("Hosted definition must explicitly enable assessment; the v0 stub is not an assessment.")
    if environment.get("DOCUMENTATION_AUTH_MODE") != "managed_identity":
        raise ValueError("Hosted assessment must explicitly use managed identity, not local CLI authentication.")
    if environment.get("HOST") != "0.0.0.0" or environment.get("PORT") != "8088":
        raise ValueError("Reviewed hosted assessment must listen on 0.0.0.0:8088.")
    settings = AssessmentSettings.from_environment(environment)
    return AssessmentAgent(settings).provenance


def validate_hosted_definition(
    definition: dict[str, Any], artifact: HostedArtifact, endpoint: str, model_version: str
) -> None:
    if definition.get("kind") != "hosted":
        raise ValueError("Primary target requires a hosted container definition.")
    if definition.get("container_configuration", {}).get("image") != artifact.image:
        raise ValueError("Hosted image must match the reviewed immutable digest.")
    if "image" in definition or "container_protocol_versions" in definition or definition.get("code_configuration"):
        raise ValueError(
            "Use the stable SDK container_configuration/protocol_versions definition, not legacy flat YAML."
        )
    if definition.get("protocol_versions") != [{"protocol": "responses", "version": "2.0.0"}]:
        raise ValueError("Hosted definition must retain P1's Responses 2.0.0 protocol.")
    if not definition.get("cpu") or not definition.get("memory"):
        raise ValueError("Reviewed hosted CPU/memory are required.")
    provenance = assessment_provenance(definition)
    if provenance != artifact.runtime_provenance:
        raise ValueError("Artifact provenance differs from P1's actual packaged settings/instructions/policy.")
    environment = definition["environment_variables"]
    if environment["DOCUMENTATION_PROJECT_ENDPOINT"] != endpoint or provenance.model_version != model_version:
        raise ValueError("Hosted project/model settings differ from the reviewed target.")
    if model_version.lower() in {"latest", "@latest", "unknown", "current", "none", "null"}:
        raise ValueError("A concrete hosted model deployment version is required.")


def validate_hosted_version(
    version: dict[str, Any], artifact: HostedArtifact, endpoint: str, model_version: str
) -> None:
    if version.get("name") != artifact.runtime_provenance.agent_name:
        raise ValueError("Hosted name differs from the reviewed P1 runtime.")
    if not re.fullmatch(r"[1-9][0-9]*", version.get("version", "")) or version.get("status") != "active":
        raise ValueError("Hosted assessment version must be concrete and active before invocation.")
    validate_hosted_definition(version["definition"], artifact, endpoint, model_version)


def result_from_response(raw: dict[str, Any], request: AgentRequest, artifact: HostedArtifact) -> AgentResult:
    if any(item.get("type") not in {"message", "reasoning"} for item in raw.get("output", [])):
        raise ValueError("Hosted assessment returned unexpected tools/approval output; no resume was sent.")
    result = AgentResult.model_validate_json(structured_text(raw))
    if result.request_id != request.request_id:
        raise ValueError("Hosted AgentResult request_id does not match this invocation.")
    if result.provenance != artifact.runtime_provenance:
        raise ValueError("Hosted runtime provenance differs from the reviewed artifact; it must not be overwritten.")
    if any(item.source == "git" and item.version != request.subject.commit_sha for item in result.evidence):
        raise ValueError("Hosted Git evidence does not match the requested commit.")
    return result


def invoke_hosted(
    project: Any, request: AgentRequest, name: str, version: str, artifact: HostedArtifact
) -> dict[str, Any]:
    from azure.ai.projects.models import VersionRefIndicator

    if name != artifact.runtime_provenance.agent_name or not re.fullmatch(r"[1-9][0-9]*", version):
        raise ValueError("Select a concrete version of the reviewed hosted runtime.")
    session = project.agents.create_session(
        agent_name=name, version_indicator=VersionRefIndicator(agent_version=version)
    )
    session_id = session.agent_session_id
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Hosted session creation returned no session ID.")
    print(json.dumps({
        "agent_session_id": session_id, "agent_version": version,
        "request_id": str(request.request_id), "correlation_id": str(request.correlation_id),
    }), file=sys.stderr)

    def require_binding() -> None:
        indicator = session.version_indicator
        if indicator.type != "version_ref" or indicator.agent_version != version:
            raise ValueError("Hosted session is not bound to the reviewed concrete version.")

    require_binding()
    deadline = time.monotonic() + 180
    while session.status in {"creating", "updating"} and time.monotonic() < deadline:
        time.sleep(2)
        session = project.agents.get_session(agent_name=name, session_id=session_id)
        if session.agent_session_id != session_id:
            raise ValueError("Hosted session readback returned a different ID.")
        require_binding()
    if session.status not in {"active", "idle"}:
        raise ValueError(f"Hosted session is not ready: {session.status!r}; retained session {session_id}.")
    with project.get_openai_client(agent_name=name) as client:
        raw = client.responses.create(
            input=request.model_dump_json(),
            extra_body={"agent_session_id": session_id},
        ).model_dump()
    if not isinstance(raw.get("id"), str) or not raw["id"].strip():
        raise ValueError("Hosted response ID is missing.")
    result = result_from_response(raw, request, artifact)
    return {
        "run_id": raw["id"],
        "response_ids": [raw["id"]],
        "agent_name": name,
        "agent_version": version,
        "agent_session_id": session_id,
        "image": artifact.image,
        "source_commit": artifact.source_commit,
        "build_reference": artifact.build_reference,
        "request_id": str(request.request_id),
        "correlation_id": str(request.correlation_id),
        "routing": "version_specific_session_not_serving_path_proof",
        "result": result.model_dump(mode="json"),
    }


def suite_blockers(cases: list[dict[str, Any]]) -> list[str]:
    blockers = []
    supplied = [case["id"] for case in cases if case["mode"] == "supplied_sources"]
    if supplied:
        blockers.append(
            "P1 assessment accepts bare AgentRequest only; no tools-disabled supplied-source input: "
            + ", ".join(supplied)
        )
    blockers.append(
        "P1 assessment does not export correlated nested tool calls, results and discovered schemas; "
        "builtin.tool_call_accuracy and pinned live-source verification cannot be certified from outer Responses."
    )
    return blockers


def evaluator_item(case: dict[str, Any], report: dict[str, Any], instructions: str) -> dict[str, Any]:
    """Groundedness/task-adherence inputs for a supported assessment, not a release pass."""
    if case["mode"] != "live_sources":
        raise ValueError("P1 hosted assessment does not support supplied-source evaluation.")
    result = AgentResult.model_validate(report["result"])
    if result.request_id != case["request"].request_id:
        raise ValueError("Hosted evaluator input belongs to another request.")
    if result.documentation_status != case["expected_status"]:
        raise ValueError("Hosted result differs from the unchanged case expectation.")
    return {
        "case_id": case["id"],
        "query": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": case["request"].model_dump_json()},
        ],
        "response": [{"role": "assistant", "content": [{"type": "text", "text": result.model_dump_json()}]}],
        "context": json.dumps(case["sources"]),
    }
