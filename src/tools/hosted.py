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


def assessment_provenance(definition: dict[str, Any], *, evaluation: bool = False) -> Provenance:
    # Use P1's settings and instruction/policy assembly, never a second contract.
    from documentation_agent.assessment import AssessmentAgent
    from documentation_agent.settings import AssessmentSettings

    environment = definition.get("environment_variables", {})
    if evaluation:
        if (
            environment.get("DOCUMENTATION_MODE") != "evaluation"
            or environment.get("DOCUMENTATION_ENABLE_EVALUATION") != "true"
        ):
            raise ValueError("Evaluation requires its explicit mode and DOCUMENTATION_ENABLE_EVALUATION=true.")
    elif environment.get("DOCUMENTATION_MODE") != "assessment":
        raise ValueError("Hosted definition must explicitly enable assessment; the v0 stub is not an assessment.")
    if environment.get("DOCUMENTATION_AUTH_MODE") != "managed_identity":
        raise ValueError("Hosted assessment must explicitly use managed identity, not local CLI authentication.")
    # Foundry reserves PORT; omission retains the reviewed Dockerfile's 8088 default.
    if environment.get("HOST") != "0.0.0.0" or environment.get("PORT", "8088") != "8088":
        raise ValueError("Reviewed hosted assessment must listen on 0.0.0.0:8088.")
    settings = AssessmentSettings.from_environment(environment)
    return AssessmentAgent(settings).provenance


def validate_hosted_definition(
    definition: dict[str, Any], artifact: HostedArtifact, endpoint: str, model_version: str,
    *, evaluation: bool = False,
) -> None:
    if definition.get("kind") != "hosted":
        raise ValueError("Primary target requires a hosted container definition.")
    if definition.get("container_configuration", {}).get("image") != artifact.image:
        raise ValueError("Hosted image must match the reviewed immutable digest.")
    # The service echoes an empty legacy container_protocol_versions list; only populated legacy keys are rejected.
    if "image" in definition or definition.get("container_protocol_versions") or definition.get("code_configuration"):
        raise ValueError(
            "Use the stable SDK container_configuration/protocol_versions definition, not legacy flat YAML."
        )
    protocols = definition.get("protocol_versions") or []
    if {"protocol": "responses", "version": "2.0.0"} not in protocols or any(
        entry not in ({"protocol": "responses", "version": "2.0.0"}, {"protocol": "activity", "version": "2.0.0"})
        for entry in protocols
    ):
        raise ValueError("Hosted definition must retain P1's Responses 2.0.0 protocol (Teams activity optional).")
    if not definition.get("cpu") or not definition.get("memory"):
        raise ValueError("Reviewed hosted CPU/memory are required.")
    provenance = assessment_provenance(definition, evaluation=evaluation)
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
    raw, report = hosted_response(project, request, name, version, artifact)
    report["result"] = result_from_response(raw, request, artifact).model_dump(mode="json")
    return report


def hosted_response(
    project: Any, request: AgentRequest, name: str, version: str, artifact: HostedArtifact,
    *, evaluation_input: str | None = None, endpoint_label_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Invoke one version-bound session.

    The live service labels the outer agent_reference with the endpoint selector's serving version even
    when the session is bound to another version. Evaluation callers may accept that serving label because
    the serving version cannot answer an EvaluationRequest; the GET-confirmed session binding stays required.
    """
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
    session = project.agents.get_session(agent_name=name, session_id=session_id)
    if session.agent_session_id != session_id or session.status not in {"active", "idle"}:
        raise ValueError("Hosted session GET does not confirm the ready created session.")
    require_binding()
    with project.get_openai_client(agent_name=name) as client:
        options = {"store": False, "stream": False} if evaluation_input is not None else {}
        raw = client.responses.create(
            input=evaluation_input if evaluation_input is not None else request.model_dump_json(),
            extra_body={"agent_session_id": session_id}, **options,
        ).model_dump()
    if not isinstance(raw.get("id"), str) or not raw["id"].strip():
        raise ValueError("Hosted response ID is missing.")
    outer_reference = raw.get("agent_reference")
    print(json.dumps({
        "response_id": raw["id"], "agent_session_id": session_id,
        "session_version_indicator": {"type": "version_ref", "agent_version": version},
        "outer_agent_reference": outer_reference,
    }), file=sys.stderr)
    labelled = {version} | ({endpoint_label_version} if endpoint_label_version else set())
    if outer_reference is not None and (
        not isinstance(outer_reference, dict)
        or outer_reference.get("type") != "agent_reference"
        or outer_reference.get("name") != name
        or outer_reference.get("version") not in labelled
    ):
        raise ValueError(
            "Hosted response agent_reference disagrees with the GET-confirmed session binding; "
            "no candidate-version success is certified. See retained session/response identifiers on stderr."
        )
    if evaluation_input is not None and outer_reference is None:
        raise ValueError(
            "Evaluation requires matching outer agent_reference and GET-confirmed session evidence; "
            "session-only metadata cannot certify candidate execution."
        )
    return raw, {
        "run_id": raw["id"],
        "response_ids": [raw["id"]],
        "agent_name": name,
        "agent_version": version,
        "agent_session_id": session_id,
        "session_version_indicator": {"type": "version_ref", "agent_version": version},
        "outer_agent_reference": outer_reference,
        "version_evidence": (
            "session_get_only" if not outer_reference
            else "session_get_and_matching_outer_reference" if outer_reference["version"] == version
            else "session_get_and_endpoint_serving_label"
        ),
        "image": artifact.image,
        "source_commit": artifact.source_commit,
        "build_reference": artifact.build_reference,
        "request_id": str(request.request_id),
        "correlation_id": str(request.correlation_id),
        "routing": "version_specific_session_not_serving_path_proof",
    }


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
            {"role": "user", "content": [{"type": "text", "text": case["request"].model_dump_json()}]},
        ],
        "response": [{"role": "assistant", "content": [{"type": "text", "text": result.model_dump_json()}]}],
        "context": json.dumps(case["sources"]),
    }
