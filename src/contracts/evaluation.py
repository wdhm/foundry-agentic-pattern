"""Opt-in hosted evaluation transport; production AgentRequest/AgentResult remain unchanged."""

import hashlib
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from .models import ContractModel, NonBlank
from .v1 import AgentRequest, AgentResult, Evidence

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SourceText = Annotated[str, Field(min_length=1, max_length=200_000)]


class SuppliedStandard(ContractModel):
    content: SourceText
    sha256: Digest

    @model_validator(mode="after")
    def matching_digest(self) -> Self:
        if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("Standard content does not match its SHA-256.")
        return self


class SourceSnapshot(ContractModel):
    id: NonBlank
    source: Literal["git", "wiki", "work_item"]
    uri: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    availability: Literal["available", "unavailable"]
    version: NonBlank | None
    content: SourceText | None
    sha256: Digest | None

    @model_validator(mode="after")
    def valid_content(self) -> Self:
        if self.availability == "unavailable":
            if any(value is not None for value in (self.version, self.content, self.sha256)):
                raise ValueError("An unavailable source must not include content, a version or a content digest.")
        else:
            if self.content is None or self.sha256 is None or self.version is None:
                raise ValueError("An available source needs content, exact version and SHA-256.")
            if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.sha256:
                raise ValueError("Source content does not match its SHA-256.")
            Evidence(id=self.id, source=self.source, uri=self.uri, version=self.version, excerpt="validation")
        return self


class EvaluationRequest(ContractModel):
    interface_version: Literal["1.0.0"]
    source_mode: Literal["live_sources", "supplied_sources"]
    request: AgentRequest
    task: Annotated[NonBlank, Field(max_length=8000)] | None = None
    standard: SuppliedStandard | None = None
    sources: Annotated[list[SourceSnapshot], Field(max_length=20)] = Field(default_factory=list)

    @model_validator(mode="after")
    def isolated_sources(self) -> Self:
        if self.source_mode == "live_sources":
            if self.sources or self.standard is not None or self.task is not None:
                raise ValueError("Live mode accepts only the production AgentRequest; no source/instruction override.")
        else:
            if self.standard is None:
                raise ValueError("Supplied-source mode requires an explicit documentation standard.")
            ids = [source.id for source in self.sources]
            identities = [(source.source, source.uri) for source in self.sources]
            if len(set(ids)) != len(ids) or len(set(identities)) != len(identities):
                raise ValueError("Snapshot IDs and source URIs must be unique.")
            for source in self.sources:
                if source.source == "git" and source.availability == "available":
                    if source.version != self.request.subject.commit_sha:
                        raise ValueError("Git snapshot version must match the request commit.")
            if (
                sum(len((source.content or "").encode()) for source in self.sources)
                + len(self.standard.content.encode())
                > 500_000
            ):
                raise ValueError("Supplied source bundle exceeds 500 KB.")
        return self


class ExecutionRecord(ContractModel):
    interface_version: Literal["1.0.0"] = "1.0.0"
    execution_id: UUID
    request_id: UUID
    correlation_id: UUID
    platform_call_id: str | None = None
    platform_session_id: str | None = None
    source_mode: Literal["live_sources", "supplied_sources"]
    status: Literal["running", "completed"] = "running"
    instructions: str
    sources: list[SourceSnapshot] = Field(default_factory=list)
    standard: SuppliedStandard | None = None
    tool_schemas: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model_calls: list[dict[str, Any]] = Field(default_factory=list)


class EvaluationResponse(ContractModel):
    interface_version: Literal["1.0.0"] = "1.0.0"
    result: AgentResult
    execution: ExecutionRecord
