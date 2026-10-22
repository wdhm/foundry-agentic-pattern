"""Immutable Azure Repos draft references shared by the pipeline and runtime."""

import hashlib
from typing import Annotated, Literal
from urllib.parse import quote, urlencode
from uuid import UUID

from pydantic import Field

from .models import CommitSha, ContractModel, NonBlank
from .repositories import azure_repository


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def draft_path(event_id: UUID) -> str:
    return f"/documentation-drafts/{event_id}.md"


def draft_branch(event_id: UUID) -> str:
    return f"refs/heads/documentation-drafts/{event_id}"


def review_path(event_id: UUID) -> str:
    return f"/documentation-drafts/{event_id}-review.md"


def pull_request_url(repository_url: str, number: int) -> str:
    azure_repository(repository_url)
    if number <= 0:
        raise ValueError("Pull request ID must be positive.")
    return f"{repository_url}/pullrequest/{number}"


def draft_url(repository_url: str, event_id: UUID, commit: str, *, review: bool = False) -> str:
    repo = azure_repository(repository_url)
    base = "https://dev.azure.com/" + "/".join(
        quote(value, safe="") for value in (repo.organization, repo.project, "_git", repo.repository)
    )
    path = review_path(event_id) if review else draft_path(event_id)
    return base + "?" + urlencode({"path": path, "version": "GC" + commit, "_a": "contents"})


class PreparedDraft(ContractModel):
    event_id: UUID
    state: Literal["draft_ready"]
    duplicate: bool
    content: Annotated[NonBlank, Field(max_length=16000)]
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    source_commit: CommitSha
    pull_request_id: Annotated[int, Field(strict=True, gt=0)]
    review_notes: Annotated[NonBlank, Field(max_length=64000)] | None = None


class DraftPublished(ContractModel):
    interface_version: Literal["1.0.0"]
    action: Literal["draft_published"]
    event_id: UUID
    draft_commit: CommitSha


class VerifiedDraft(ContractModel):
    commit: CommitSha
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
