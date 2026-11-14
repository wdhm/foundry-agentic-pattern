"""Merge a source-verified diagram proposal without changing publication authority."""

import asyncio
import json
from typing import Any

from pydantic import ValidationError

from contracts.evidence import source_records, trace_evidence_problems
from contracts.v1 import AgentRequest, AgentResult, VisualizationReview
from contracts.visualization import DiagramEdge, DiagramNode, VisualizationRequest, VisualizationSource

from .visualization_agent_client import VisualizationClient
from .visualization_settings import VisualizationSettings
from .wiki_page import headings, section_key, section_updates

MAX_HANDOFF_BYTES = 96000


def current_section(content: str, title: str) -> str | None:
    parsed = headings(content)
    matches = [heading for heading in parsed if heading.level == 2 and section_key(heading.title) == section_key(title)]
    if len(matches) > 1:
        raise ValueError("Duplicate architecture diagram sections require manual review.")
    if not matches:
        if "```mermaid" in content or "::: mermaid" in content or ":::mermaid" in content:
            raise ValueError("Move the existing diagram into the Architecture diagram section before enabling A2A.")
        return None
    heading = matches[0]
    end = next((h.start for h in parsed if h.start > heading.start and h.level <= 2), len(content))
    body = content[heading.body_start:end]
    if not any(marker in body for marker in ("```mermaid", "::: mermaid", ":::mermaid")):
        raise ValueError("Architecture diagram section has no Mermaid diagram; review it before enabling A2A.")
    return body


def handoff(
    request: AgentRequest, result: AgentResult, calls: list[dict[str, Any]], settings: VisualizationSettings,
) -> VisualizationRequest:
    if settings.target_page not in request.context.wiki_page_paths:
        raise ValueError("Visualization target page is outside the assessment request.")
    for change in result.proposed_changes:
        for title, _ in section_updates(change.target_section, change.proposed_content):
            if section_key(title) == section_key(settings.target_section):
                raise ValueError("The architecture diagram section belongs exclusively to the visualization agent.")
        if any(marker in change.proposed_content for marker in ("```mermaid", ":::mermaid", "::: mermaid")):
            raise ValueError("Documentation assessment cannot author a second Mermaid diagram.")
    wiki_records = []
    for call in calls:
        if call.get("server_label") == "ado" and call.get("name") == "wiki":
            args = json.loads(call["arguments"])
            if args.get("path") == settings.target_page:
                wiki_records.extend(source_records({"output": [call]}))
    if not wiki_records or any(
        (item["content"], item["version"], item["uris"]) !=
        (wiki_records[0]["content"], wiki_records[0]["version"], wiki_records[0]["uris"])
        for item in wiki_records
    ):
        raise ValueError("Visualization needs one consistently versioned target wiki read.")
    sources: list[VisualizationSource] = []
    for record in source_records({"output": calls}):
        uris = [uri for uri in record["uris"] if uri.startswith("https://")]
        if not uris or not record["content"].strip():
            raise ValueError("Visualization source content or URI is unavailable.")
        item = VisualizationSource.model_validate({
            "source": record["source"], "uri": uris[0],
            "version": record["version"], "content": record["content"],
        })
        if item not in sources:
            sources.append(item)
    payload = VisualizationRequest(
        request_id=request.request_id, correlation_id=request.correlation_id,
        subject=request.subject, task=request.task, target_page=settings.target_page,
        current_section=current_section(wiki_records[0]["content"], settings.target_section),
        sources=sources, guidelines_version=settings.guidelines_version,
    )
    if len(payload.model_dump_json().encode("utf-8")) > MAX_HANDOFF_BYTES:
        raise ValueError("Visualization source package exceeds the size limit; no truncation is allowed.")
    return payload


async def add_visualization(
    request: AgentRequest, result: AgentResult, calls: list[dict[str, Any]],
    settings: VisualizationSettings, client: VisualizationClient,
) -> AgentResult:
    """Assess the diagram and add any validated proposal to the documentation result."""
    payload = handoff(request, result, calls, settings)
    async with asyncio.timeout(settings.timeout_seconds):
        output = await client.review(payload)
    if (
        output.request_id != request.request_id or output.input_sha256 != payload.input_sha256
        or output.guidelines_version != settings.guidelines_version
    ):
        raise ValueError("Visualization response does not match the request, sources or guidelines version.")
    if output.decision == "create" and payload.current_section is not None:
        raise ValueError("Cannot create a diagram over an existing diagram.")
    if output.decision in {"keep", "update"} and payload.current_section is None:
        raise ValueError("Cannot keep or update a missing diagram.")
    allowed = {(source.source, source.uri, source.version.strip('"')) for source in payload.sources}
    if any((item.source, item.uri, item.version.strip('"')) not in allowed for item in output.evidence):
        raise ValueError("Visualization evidence references a source outside its handoff.")
    problems = trace_evidence_problems({"output": calls}, output.model_dump(mode="json"))
    if problems:
        raise ValueError("Visualization evidence verification failed: " + "; ".join(problems))
    if output.decision != "insufficient_context" and not any(item.source == "git" for item in output.evidence):
        raise ValueError("Architecture decisions require implementation evidence, not just the current wiki.")
    data = result.model_dump(mode="json")
    remap = {item.id: f"visualization-{item.id}" for item in output.evidence}
    if set(remap.values()) & {item.id for item in result.evidence}:
        raise ValueError("Visualization evidence IDs collide with assessment evidence.")
    data["evidence"].extend({**item.model_dump(), "id": remap[item.id]} for item in output.evidence)
    if output.diagram is not None:
        elements: list[DiagramNode | DiagramEdge] = [*output.diagram.nodes, *output.diagram.edges]
        refs = sorted({remap[ref] for item in elements for ref in item.evidence_refs})
        content = "```mermaid\n" + output.diagram.mermaid() + "\n```"
        if payload.current_section is not None and payload.current_section.strip().replace("\r\n", "\n") == content:
            raise ValueError("An unchanged diagram must use keep, not update.")
        data["proposed_changes"].append({
            "target_page": settings.target_page, "target_section": settings.target_section,
            "proposed_content": content,
            "evidence_refs": refs,
        })
        data["findings"].append({
            "category": "Architecture diagram", "severity": "low",
            "description": output.reason, "evidence_refs": refs,
        })
        data["requires_human_review"] = True
        if data["documentation_status"] != "insufficient_information":
            data["documentation_status"] = "gaps_found"
    if output.decision == "insufficient_context":
        data["missing_information"].extend({
            "description": item, "expected_source": "Versioned implementation sources for architecture visualization",
        } for item in output.missing_information)
        data["documentation_status"] = "insufficient_information"
    data["visualization"] = VisualizationReview(
        decision=output.decision, reason=output.reason, agent_name=settings.agent_name,
        agent_card_version=settings.card_version, guidelines_version=settings.guidelines_version,
        input_sha256=payload.input_sha256,
    ).model_dump()
    try:
        return AgentResult.model_validate(data)
    except ValidationError:
        raise ValueError("Combined documentation and visualization result is invalid.") from None
