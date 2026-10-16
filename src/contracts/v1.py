import re
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from .models import ContractModel, NonBlank, RequestContext, Subject

CONTRACT_VERSION: Final[Literal["1.0.0"]] = "1.0.0"
EvidenceRefs = Annotated[list[NonBlank], Field(min_length=1)]


class AgentRequest(ContractModel):
    contract_version: Literal["1.0.0"]
    request_id: UUID
    correlation_id: UUID
    trigger: NonBlank
    requested_by: NonBlank
    subject: Subject
    context: RequestContext = Field(default_factory=RequestContext)
    documentation_standard_ref: NonBlank


class Provenance(ContractModel):
    agent_name: NonBlank
    agent_version: NonBlank
    model: NonBlank
    model_version: NonBlank
    prompt_version: NonBlank
    policy_version: NonBlank
    contract_version: Literal["1.0.0"]


class Evidence(ContractModel):
    id: NonBlank
    source: Literal["git", "wiki", "work_item"]
    uri: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    version: NonBlank = Field(description="Exact Git SHA, wiki ETag/version, or work-item revision; never a branch.")
    excerpt: NonBlank

    @model_validator(mode="after")
    def exact_version(self) -> Self:
        if self.version.strip().lower() in {"latest", "main", "master", "head", "unknown", "current"}:
            raise ValueError("Evidence must pin an exact source version, not a moving reference.")
        if self.source == "git" and re.fullmatch(r"[0-9a-fA-F]{40}", self.version) is None:
            raise ValueError("Git evidence requires a full 40-character commit SHA.")
        if self.source == "work_item" and re.fullmatch(r"[1-9][0-9]*", self.version) is None:
            raise ValueError("Work-item evidence requires a positive integer revision.")
        return self


class Finding(ContractModel):
    category: NonBlank
    severity: Literal["low", "medium", "high", "critical"]
    description: NonBlank
    evidence_refs: EvidenceRefs


class ProposedChange(ContractModel):
    target_page: NonBlank
    target_section: NonBlank
    proposed_content: NonBlank
    evidence_refs: EvidenceRefs


class MissingInformation(ContractModel):
    description: NonBlank
    expected_source: NonBlank


class AnalysisOutput(ContractModel):
    """Model-authored fields only; the caller supplies correlation and provenance."""

    documentation_status: Literal["up_to_date", "gaps_found", "insufficient_information"]
    findings: list[Finding]
    proposed_changes: list[ProposedChange]
    missing_information: list[MissingInformation]
    evidence: list[Evidence]
    confidence: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    requires_human_review: bool = Field(strict=True)

    @model_validator(mode="after")
    def consistent_analysis(self) -> Self:
        ids = [item.id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique.")
        referenced_items: list[Finding | ProposedChange] = [*self.findings, *self.proposed_changes]
        for item in referenced_items:
            if not set(item.evidence_refs).issubset(ids):
                raise ValueError("Every evidence reference must resolve to an evidence ID.")
        if self.proposed_changes and not self.requires_human_review:
            raise ValueError("Proposed changes require human review; this field is not approval.")
        if self.documentation_status == "up_to_date":
            if self.findings or self.proposed_changes or self.missing_information or not self.evidence:
                raise ValueError("Up-to-date status needs evidence and no outstanding findings, changes or unknowns.")
        if self.documentation_status == "gaps_found" and not self.findings:
            raise ValueError("Gaps-found status requires findings.")
        if self.documentation_status == "insufficient_information" and not self.missing_information:
            raise ValueError("Insufficient-information status requires an explanation of what is missing.")
        return self


class AgentResult(AnalysisOutput):
    contract_version: Literal["1.0.0"]
    request_id: UUID
    provenance: Provenance


def assemble_result(request: AgentRequest, output: AnalysisOutput, provenance: Provenance) -> AgentResult:
    return AgentResult(
        **output.model_dump(),
        contract_version=CONTRACT_VERSION,
        request_id=request.request_id,
        provenance=provenance,
    )
