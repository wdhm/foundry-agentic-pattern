"""Strict handoffs. Golden facts are authored by engineers, never generated here."""

import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from contracts.repositories import AzureRepository
from tools.sandbox_eval import Identity, Name, Pin, StrictModel

Text = Annotated[str, Field(min_length=1, max_length=16000, pattern=r"\S")]
Id = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$")]
Category = Literal["auth", "endpoint", "config", "schedule", "error_handling", "data", "infra", "other"]
Severity = Literal["critical", "normal"]


def valid_path(path: str) -> str:
    if (
        not path.startswith("/") or any(c in path for c in "\\%?#")
        or any(p in {"", ".", ".."} or any(ord(c) < 32 for c in p) for p in path[1:].split("/"))
    ):
        raise ValueError("An exact absolute Git path without encoded separators or traversal is required.")
    return path


class Repo(StrictModel):
    id: Id
    organization: Name
    project: Name
    repository: Name
    commit: Pin

    @property
    def azure(self) -> AzureRepository:
        return AzureRepository(self.organization, self.project, self.repository)

    @property
    def key(self) -> str:
        return f"{self.organization}/{self.project}/{self.repository}@{self.commit}"


class Quote(StrictModel):
    file: Text
    line: int = Field(ge=1)
    text: Text


class Fact(StrictModel):
    fact_id: Id
    fact: Text
    severity: Severity
    category: Category
    source: Quote


class Page(StrictModel):
    repo: Repo
    path: Text
    origin: Literal["existing_wiki_page", "approved_agent_generated_page"]
    provenance_reference: Text

    @model_validator(mode="after")
    def path_check(self) -> Self:
        valid_path(self.path)
        if not self.path.endswith(".md"):
            raise ValueError("Page must name the actual Markdown file in the wiki backing Git repository.")
        return self


class Case(StrictModel):
    id: Id
    integration_repo: Repo
    merge_commit: Pin
    base_commit: Pin
    related_repos: list[Repo] = Field(default_factory=list, max_length=8)
    page: Page
    critical_facts: list[Fact] = Field(min_length=1, max_length=100)
    facts_author: Text
    facts_review_reference: Text

    @property
    def repos(self) -> list[Repo]:
        return [self.integration_repo, *self.related_repos]

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.merge_commit != self.integration_repo.commit or self.base_commit == self.merge_commit:
            raise ValueError("Integration commit must equal merge_commit, with a different pinned diff base.")
        if len({r.id for r in self.repos}) != len(self.repos) or len({r.key for r in self.repos}) != len(self.repos):
            raise ValueError("Code repository IDs and coordinates must be unique.")
        if len({f.fact_id for f in self.critical_facts}) != len(self.critical_facts):
            raise ValueError("Fact IDs must be unique.")
        if not any(f.severity == "critical" for f in self.critical_facts):
            raise ValueError("Golden testing requires engineer-authored critical facts.")
        return self


class Manifest(StrictModel):
    schema_version: Literal["1"]
    read_identity: Identity
    read_approval_reference: Text
    cases: list[Case] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Case IDs must be unique.")
        return self


class IdentityFile(StrictModel):
    read_identity: Identity


class Deployment(StrictModel):
    deployment: Name
    model: Text
    version: Text


class Config(StrictModel):
    schema_version: Literal["1"]
    project_endpoint: Text
    serving_project_endpoint: Text
    model_identity: Identity
    isolation_review_reference: Text
    source_exposure_approval_reference: Text
    candidate: Deployment
    extractor: Deployment
    verifier: Deployment
    seed: int = 42
    normal_sample: int = Field(default=10, ge=0, le=50)
    max_files: int = Field(default=500, ge=1, le=5000)
    max_source_bytes: int = Field(default=8_000_000, ge=1, le=20_000_000)
    max_requests: int = Field(default=600, ge=1, le=6000)
    max_calls: int = Field(default=100, ge=1, le=1000)
    max_input_bytes: int = Field(default=100_000, ge=1000, le=150_000)
    max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    timeout_seconds: int = Field(default=60, ge=1, le=180)
    run_timeout_seconds: int = Field(default=1200, ge=1, le=2400)
    evidence_bytes: int = Field(default=24000, ge=1000, le=28000)

    @model_validator(mode="after")
    def isolated(self) -> Self:
        for value in (self.project_endpoint, self.serving_project_endpoint):
            url = urlsplit(value)
            if (
                url.scheme != "https" or not url.netloc.endswith(".services.ai.azure.com")
                or not re.fullmatch(r"/api/projects/[A-Za-z0-9._-]+/?", url.path)
                or url.query or url.fragment or url.username or url.port
            ):
                raise ValueError("Explicit direct Foundry project endpoints are required.")
        if self.project_endpoint.rstrip("/") == self.serving_project_endpoint.rstrip("/"):
            raise ValueError("Evaluation must use a separate isolated project.")
        if (
            self.verifier.deployment == self.candidate.deployment
            or (self.verifier.model, self.verifier.version) == (self.candidate.model, self.candidate.version)
        ):
            raise ValueError("Verifier must use a different deployment and model/version from the candidate.")
        return self


class Claim(StrictModel):
    claim_id: Id
    claim: Text
    source_sentence: Text
    section: Text
    severity: Severity
    category: Category


class Claims(StrictModel):
    claims: list[Claim] = Field(max_length=200)


class PrecisionVerdict(StrictModel):
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_VERIFIABLE"]
    evidence_quotes: list[Quote] = Field(max_length=20)
    reason: Text


class RecallVerdict(StrictModel):
    verdict: Literal["STATED", "WRONG", "MISSING"]
    page_quote: str = Field(max_length=16000)
    reason: Text
