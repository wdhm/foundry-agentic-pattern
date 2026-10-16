"""Invoke an exact hosted assessment version; prompt is an explicit compatibility path."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from contracts.models import RequestContext, Subject
from contracts.prompt import OUTPUT_INSTRUCTIONS, structured_format
from contracts.v1 import CONTRACT_VERSION, AgentRequest, AnalysisOutput, Provenance, assemble_result

if TYPE_CHECKING:
    from openai import OpenAI


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    invoke = root.add_subparsers(dest="command", required=True).add_parser("invoke")
    invoke.add_argument("--project-endpoint", required=True)
    invoke.add_argument("--agent-kind", choices=("hosted", "prompt"), default="hosted")
    invoke.add_argument("--agent-name")
    invoke.add_argument("--artifact", type=Path, help="Reviewed hosted image/build/runtime provenance JSON.")
    invoke.add_argument("--agent-version", required=True, help="Exact positive integer version; never latest.")
    invoke.add_argument("--model-version", required=True, help="Exact version verified in deployment configuration.")
    invoke.add_argument("--repo", required=True, help="Repository URL or owner/repository.")
    invoke.add_argument("--commit", required=True, help="Full 40-character commit SHA.")
    invoke.add_argument("--path", action="append", default=[], help="Changed path; repeat as needed.")
    invoke.add_argument("--pr-reference")
    invoke.add_argument("--wiki-page", action="append", default=[])
    invoke.add_argument("--work-item", action="append", type=int, default=[])
    invoke.add_argument("--adr-ref", action="append", default=[])
    invoke.add_argument("--documentation-standard-ref", required=True)
    invoke.add_argument("--requested-by", required=True)
    invoke.add_argument("--request-id", type=UUID)
    invoke.add_argument("--correlation-id", type=UUID)
    return root


def build_request(args: argparse.Namespace) -> AgentRequest:
    return AgentRequest(
        contract_version=CONTRACT_VERSION,
        request_id=args.request_id or uuid4(),
        correlation_id=args.correlation_id or uuid4(),
        trigger="cli",
        requested_by=args.requested_by,
        subject=Subject(
            repo=args.repo,
            commit_sha=args.commit,
            changed_paths=args.path,
            pr_reference=args.pr_reference,
        ),
        context=RequestContext(
            wiki_page_paths=args.wiki_page,
            work_item_ids=args.work_item,
            adr_refs=args.adr_ref,
        ),
        documentation_standard_ref=args.documentation_standard_ref,
    )


def selected_provenance(
    name: str,
    version: str,
    definition: dict[str, Any],
    metadata: dict[str, str],
    model_version: str,
) -> Provenance:
    if definition.get("kind") != "prompt":
        raise ValueError("The prompt compatibility path requires a prompt definition.")
    if definition.get("text", {}).get("format") != structured_format():
        raise ValueError("The selected version must already have the current AnalysisOutput v1 schema.")
    instructions = definition.get("instructions") or ""
    if OUTPUT_INSTRUCTIONS not in instructions:
        raise ValueError("The selected version must retain the shared assessment-only policy; ask P1 to configure it.")
    if metadata.get("contract_version") != CONTRACT_VERSION or not metadata.get("policy_version"):
        raise ValueError("The selected version needs contract_version=1.0.0 and truthful policy_version metadata.")
    for tool in definition.get("tools", []):
        if tool.get("type") != "mcp":
            raise ValueError("This trigger supports the existing MCP prompt-agent tools only.")
        allowed = tool.get("allowed_tools")
        if isinstance(allowed, dict):
            allowed = allowed.get("tool_names")
        if tool.get("server_label") == "ado" and (allowed is None or "wiki_upsert_page" in allowed):
            approval = tool.get("require_approval")
            if approval != "always":
                if not isinstance(approval, dict):
                    raise ValueError("wiki_upsert_page must require native approval; no invocation was sent.")
                always = approval.get("always", {}).get("tool_names", [])
                never = approval.get("never", {}).get("tool_names", [])
                if "wiki_upsert_page" not in always or "wiki_upsert_page" in never:
                    raise ValueError("wiki_upsert_page must require native approval; no invocation was sent.")
    return Provenance(
        contract_version=CONTRACT_VERSION,
        agent_name=name,
        agent_version=version,
        model=definition["model"],
        model_version=model_version,
        prompt_version="sha256:" + hashlib.sha256(instructions.encode()).hexdigest(),
        policy_version=metadata["policy_version"],
    )


def review_approval(item: dict[str, Any]) -> bool:
    for key in ("id", "server_label", "name", "arguments"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(f"Approval request is missing {key}; cannot safely review it.")
    # JSON escaping prevents untrusted tool arguments from controlling the terminal.
    print("Native MCP approval request:\n" + json.dumps(item, indent=2, ensure_ascii=True), file=sys.stderr)
    if not sys.stdin.isatty():
        raise ValueError("Approval requires an interactive human terminal. No approval or resume was sent.")
    print("Review the server, tool and full arguments. Type Approve or Reject: ", end="", file=sys.stderr, flush=True)
    try:
        decision = input().strip()
    except EOFError as exc:
        raise ValueError("Approval input ended. No approval or resume was sent.") from exc
    if decision not in {"Approve", "Reject"}:
        raise ValueError("Expected explicit Approve or Reject. No approval or resume was sent.")
    return decision == "Approve"


def check_tool_errors(response: dict[str, Any]) -> None:
    for item in response.get("output", []):
        kind = item.get("type")
        if kind in {"mcp_call", "mcp_list_tools"} and (
            item.get("error") or item.get("status") in {"failed", "incomplete", "in_progress"}
        ):
            raise ValueError(f"MCP tool execution/discovery failed ({kind}); inspect the Foundry run.")


def structured_text(response: dict[str, Any]) -> str:
    if response.get("status") != "completed" or response.get("error"):
        raise ValueError(f"Agent response did not complete successfully: {response.get('status')!r}.")
    check_tool_errors(response)
    texts: list[str] = []
    for item in response.get("output", []):
        kind = item.get("type")
        if kind in {"mcp_call", "mcp_list_tools"}:
            continue
        elif kind == "reasoning":
            continue
        elif kind == "message" and item.get("role") == "assistant":
            if item.get("status") not in {None, "completed"}:
                raise ValueError("Assistant message is not complete.")
            for content in item.get("content", []):
                if content.get("type") != "output_text":
                    raise ValueError("Agent refused or returned non-text output; no AgentResult was produced.")
                texts.append(content["text"])
        else:
            raise ValueError(f"Unsupported or pending response output: {kind!r}.")
    if len(texts) != 1:
        raise ValueError("Expected exactly one structured output.")
    return texts[0]


def analysis_from_response(response: dict[str, Any]) -> AnalysisOutput:
    return AnalysisOutput.model_validate_json(structured_text(response))


def invoke(client: "OpenAI", request: AgentRequest, provenance: Provenance) -> dict[str, Any]:
    from openai.types.responses.response_input_param import McpApprovalResponse, ResponseInputParam

    reference = {
        "agent_reference": {
            "type": "agent_reference",
            "name": provenance.agent_name,
            "version": provenance.agent_version,
        }
    }
    metadata = {"request_id": str(request.request_id), "correlation_id": str(request.correlation_id)}
    print(json.dumps(metadata), file=sys.stderr)
    response = client.responses.create(
        input="Assess the documentation for this AgentRequest. Read the referenced sources at their exact versions. "
        "Produce proposals only; do not write or publish anything.\n" + request.model_dump_json(),
        metadata=metadata,
        extra_body=reference,
    )
    response_ids: list[str] = []
    handled: set[str] = set()
    while True:
        if not response.id or response.id in response_ids:
            raise ValueError("Missing or repeated response ID; cannot correlate or resume this run.")
        response_ids.append(response.id)
        print(json.dumps({"response_id": response.id, **metadata}), file=sys.stderr)
        raw = response.model_dump()
        if raw.get("status") not in {"completed", "incomplete"} or raw.get("error"):
            raise ValueError(f"Agent response failed or is not ready: {raw.get('status')!r}.")
        check_tool_errors(raw)
        approvals = [item for item in raw.get("output", []) if item.get("type") == "mcp_approval_request"]
        if not approvals:
            break
        inputs: ResponseInputParam = []
        for item in approvals:
            approval_id = item.get("id")
            if not isinstance(approval_id, str) or approval_id in handled:
                raise ValueError("Missing or repeated approval request ID; no resume was sent.")
            approve = review_approval(item)
            handled.add(approval_id)
            inputs.append(
                McpApprovalResponse(type="mcp_approval_response", approval_request_id=approval_id, approve=approve)
            )
        response = client.responses.create(
            input=inputs,
            previous_response_id=response.id,
            metadata=metadata,
            extra_body=reference,
        )
    result = assemble_result(request, analysis_from_response(raw), provenance)
    return {
        "run_id": response_ids[0],
        "response_ids": response_ids,
        **metadata,
        "result": result.model_dump(mode="json"),
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        request = build_request(args)
        if not re.fullmatch(r"[1-9][0-9]*", args.agent_version):
            raise ValueError("--agent-version must be an exact positive integer, not latest or a selector.")
        if args.model_version.strip().lower() in {"", "latest", "unknown", "current"}:
            raise ValueError("--model-version must be the exact version from deployment configuration.")
        if args.agent_kind == "hosted" and args.artifact is None:
            raise ValueError("Hosted assessment requires --artifact with reviewed immutable image/build provenance.")
        args.agent_name = args.agent_name or ("documentation-agent" if args.agent_kind == "hosted" else "doc-agent")
        from azure.ai.projects import AIProjectClient
        from azure.identity import AzureCliCredential
    except (ValueError, ImportError) as exc:
        print(
            f"documentation-trigger: {exc}. Install .[agent,prompt] for hosted or .[prompt] for compatibility.",
            file=sys.stderr,
        )
        return 1

    from azure.core.exceptions import AzureError
    from openai import OpenAIError

    try:
        with (
            AzureCliCredential() as credential,
            AIProjectClient(endpoint=args.project_endpoint, credential=credential) as project,
        ):
            agent = project.agents.get_version(args.agent_name, args.agent_version)
            if agent.name != args.agent_name or agent.version != args.agent_version:
                raise ValueError("Foundry returned a different agent name/version than requested.")
            if args.agent_kind == "hosted":
                from tools.hosted import HostedArtifact, invoke_hosted, validate_hosted_version

                artifact = HostedArtifact.model_validate_json(args.artifact.read_text(encoding="utf-8"))
                validate_hosted_version(agent.as_dict(), artifact, args.project_endpoint, args.model_version)
                actual_model = project.deployments.get(artifact.runtime_provenance.model).as_dict().get("model_version")
                if actual_model != args.model_version:
                    raise ValueError("Hosted model deployment differs from the reviewed model version.")
                report = invoke_hosted(project, request, agent.name, agent.version, artifact)
            else:
                provenance = selected_provenance(
                    agent.name, agent.version, agent.definition.as_dict(), agent.metadata or {}, args.model_version
                )
                with project.get_openai_client() as client:
                    report = invoke(client, request, provenance)
        print(json.dumps(report, indent=2))
        return 0
    except (ValueError, AzureError, OpenAIError, OSError, ImportError) as exc:
        print(f"documentation-trigger: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
