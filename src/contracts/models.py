from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CONTRACT_VERSION: Final[Literal["0.1.0"]] = "0.1.0"

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Subject(ContractModel):
    repo: NonBlank = Field(description="Repository URL or owner/repository identifier.")
    commit_sha: CommitSha = Field(description="Full Git commit SHA; branches and short SHAs are not accepted.")
    changed_paths: list[NonBlank] = Field(default_factory=list)
    pr_reference: NonBlank | None = None


class RequestContext(ContractModel):
    wiki_page_paths: list[NonBlank] = Field(default_factory=list)
    work_item_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(default_factory=list)
    adr_refs: list[NonBlank] = Field(default_factory=list)


class AgentRequest(ContractModel):
    contract_version: Literal["0.1.0"]
    request_id: UUID
    correlation_id: UUID
    trigger: NonBlank = Field(description="Adapter-defined trigger name, for example cli or github_pr.")
    requested_by: NonBlank
    subject: Subject
    context: RequestContext = Field(default_factory=RequestContext)
    documentation_standard_ref: NonBlank


class Provenance(ContractModel):
    agent_name: NonBlank
    agent_version: NonBlank
    model: NonBlank = Field(description="Model deployment name.")
    model_version: NonBlank
    prompt_version: NonBlank
    policy_version: NonBlank
    contract_version: Literal["0.1.0"]


class AgentResult(ContractModel):
    contract_version: Literal["0.1.0"]
    request_id: UUID
    provenance: Provenance
