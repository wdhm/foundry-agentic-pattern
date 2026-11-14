"""Bounded handoff to an independently managed architecture visualization agent."""

import hashlib
import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from .models import ContractModel, NonBlank, Subject
from .v1 import AssessmentTask, Evidence

Label = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9 .,:()/+_-]{0,79}$")]
NodeId = Annotated[str, StringConstraints(pattern=r"^n[0-9]{1,3}$")]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Refs = Annotated[list[NonBlank], Field(min_length=1, max_length=20)]
Decision = Literal["keep", "create", "update", "insufficient_context"]


class DiagramNode(ContractModel):
    id: NodeId
    label: Label
    kind: Literal["component", "external", "store"]
    evidence_refs: Refs


class DiagramEdge(ContractModel):
    source: NodeId
    target: NodeId
    label: Label
    evidence_refs: Refs


class ArchitectureDiagram(ContractModel):
    direction: Literal["LR", "TB"]
    nodes: Annotated[list[DiagramNode], Field(min_length=1, max_length=12)]
    edges: Annotated[list[DiagramEdge], Field(max_length=24)]

    @model_validator(mode="after")
    def valid_graph(self) -> Self:
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Diagram node IDs must be unique.")
        pairs = [(edge.source, edge.target) for edge in self.edges]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate diagram connections are not supported.")
        if any(edge.source not in ids or edge.target not in ids for edge in self.edges):
            raise ValueError("Every connection must reference declared nodes.")
        return self

    def mermaid(self) -> str:
        # A closed grammar avoids model-supplied directives, links, HTML and scripts.
        shapes = {"component": ('["', '"]'), "external": ('(["', '"])'), "store": ('[("', '")]')}
        lines = [f"graph {self.direction};"]
        for node in self.nodes:
            opening, closing = shapes[node.kind]
            lines.append(f"    {node.id}{opening}{node.label}{closing};")
        lines.extend(f'    {edge.source} -->|"{edge.label}"| {edge.target};' for edge in self.edges)
        return "\n".join(lines)


class VisualizationSource(ContractModel):
    source: Literal["git", "wiki", "work_item"]
    uri: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    version: NonBlank
    content: Annotated[NonBlank, Field(max_length=32000)]


class VisualizationRequest(ContractModel):
    interface_version: Literal["1.0.0"] = "1.0.0"
    request_id: UUID
    correlation_id: UUID
    subject: Subject
    task: AssessmentTask | None
    target_page: NonBlank
    target_section: Literal["Architecture diagram"] = "Architecture diagram"
    current_section: Annotated[str | None, Field(max_length=16000)]
    sources: Annotated[list[VisualizationSource], Field(min_length=1, max_length=40)]
    guidelines_version: NonBlank

    @property
    def input_sha256(self) -> str:
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(content.encode()).hexdigest()


class VisualizationOutput(ContractModel):
    request_id: UUID
    input_sha256: Hash
    guidelines_version: NonBlank
    decision: Decision
    reason: Annotated[NonBlank, Field(max_length=2000)]
    diagram: ArchitectureDiagram | None
    evidence: Annotated[list[Evidence], Field(max_length=60)]
    missing_information: Annotated[list[NonBlank], Field(max_length=10)]

    @model_validator(mode="after")
    def consistent_decision(self) -> Self:
        if (self.decision in {"create", "update"}) != (self.diagram is not None):
            raise ValueError("Only create/update decisions must include a diagram.")
        if (self.decision == "insufficient_context") != bool(self.missing_information):
            raise ValueError("Only insufficient_context must identify missing information.")
        ids = [item.id for item in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("Visualization evidence IDs must be unique.")
        if self.decision != "insufficient_context" and not ids:
            raise ValueError("A visualization decision requires source evidence.")
        if self.diagram is not None:
            elements: list[DiagramNode | DiagramEdge] = [*self.diagram.nodes, *self.diagram.edges]
            for item in elements:
                if not set(item.evidence_refs).issubset(ids):
                    raise ValueError("Every diagram element must reference supplied evidence.")
        return self
