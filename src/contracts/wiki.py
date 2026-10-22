"""Exact existing-page snapshot and conditional-write token."""

import hashlib
from typing import Annotated, Self

from pydantic import Field, model_validator

from .models import ContractModel, NonBlank

WikiETag = Annotated[str, Field(pattern=r'^(?:[a-fA-F0-9]{40}|"[a-fA-F0-9]{40}")$')]


class WikiSnapshot(ContractModel):
    path: NonBlank
    content: Annotated[str, Field(max_length=64000)]
    etag: WikiETag
    uri: Annotated[str, Field(pattern=r"^https://dev\.azure\.com/[^\s]+$")]

    @model_validator(mode="after")
    def content_matches_etag(self) -> Self:
        body = self.content.encode("utf-8")
        blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        if self.etag.strip('"').lower() != blob:
            raise ValueError("Wiki content does not match its Git-blob ETag.")
        return self


class WikiDraftBundle(ContractModel):
    page: WikiSnapshot
    notes: WikiSnapshot | None = None
