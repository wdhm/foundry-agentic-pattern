"""Verify a completed Azure Repos PR and publish its draft on an isolated branch."""

import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from contracts.drafts import PreparedDraft, content_hash, draft_branch, draft_path, review_path
from contracts.repositories import azure_repository


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise ValueError("Azure DevOps redirect refused; do not forward the job token to another endpoint.")


class AzureDraftClient:
    def __init__(self, repository_url: str) -> None:
        repo = azure_repository(repository_url)
        UUID(repo.repository)
        self.repository_id = repo.repository
        self.repository_url = repository_url
        self.base = "https://dev.azure.com/" + "/".join(
            quote(part, safe="") for part in (
                repo.organization, repo.project, "_apis", "git", "repositories", repo.repository,
            )
        )
        self._opener = build_opener(NoRedirect())

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        token = os.environ.get("SYSTEM_ACCESSTOKEN")
        if not token:
            raise ValueError("Merged-PR draft publication requires the pipeline's scoped SYSTEM_ACCESSTOKEN.")
        request = Request(
            self.base + path, method=method, data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=90) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(
                f"Azure Repos returned HTTP {exc.code}; inspect permissions or the draft branch before retry."
            ) from None
        if not isinstance(result, dict):
            raise ValueError("Azure Repos returned an unexpected response shape.")
        return result

    def completed_pr(self, commit: str) -> int | None:
        """Only actual completed PRs with this resulting commit qualify; no commit-message heuristic."""
        matches: set[int] = set()
        for page in range(100):
            query = urlencode({
                "searchCriteria.status": "completed", "searchCriteria.targetRefName": "refs/heads/main",
                "$top": 100, "$skip": page * 100, "api-version": "7.1",
            })
            response = self.request("GET", "/pullrequests?" + query)
            values = response.get("value")
            if not isinstance(values, list):
                raise ValueError("Invalid completed PR inventory.")
            for value in values:
                if not isinstance(value, dict):
                    raise ValueError("Malformed pull request.")
                if value.get("lastMergeCommit", {}).get("commitId") == commit:
                    number = value.get("pullRequestId")
                    if type(number) is not int or number <= 0:
                        raise ValueError("Completed PR has no valid identifier.")
                    matches.add(number)
            if len(values) < 100:
                break
        else:
            raise ValueError("Completed PR inventory exceeds the bound; refusing to misclassify the push.")
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("Commit matches multiple completed PRs; do not guess.")
        number = matches.pop()
        verified = self.request("GET", f"/pullrequests/{number}?api-version=7.1")
        if (
            verified.get("status") != "completed" or verified.get("mergeStatus") != "succeeded"
            or verified.get("targetRefName") != "refs/heads/main"
            or verified.get("lastMergeCommit", {}).get("commitId") != commit
            or verified.get("repository", {}).get("id", "").lower() != self.repository_id.lower()
        ):
            raise ValueError("Pull request no longer confirms the expected successful merge to main.")
        return number

    def draft_commit(self, draft: PreparedDraft) -> str | None:
        name = draft_branch(draft.event_id)
        result = self.request("GET", "/refs?" + urlencode({
            "filter": name.removeprefix("refs/"), "api-version": "7.1",
        }))
        values = result.get("value")
        if not isinstance(values, list):
            raise ValueError("Invalid draft ref inventory.")
        exact = [value for value in values if value.get("name") == name]
        if not exact:
            return None
        if len(exact) != 1:
            raise ValueError("Ambiguous draft ref.")
        commit = exact[0]["objectId"]
        if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise ValueError("Invalid draft commit SHA.")
        metadata = self.request("GET", f"/commits/{commit}?api-version=7.1")
        if metadata.get("parents") != [draft.source_commit]:
            raise ValueError("Draft branch was edited or has a different base; never overwrite it.")
        for path, content in self.files(draft):
            file = self.request("GET", "/items?" + urlencode({
                "path": path, "includeContent": "true",
                "versionDescriptor.version": commit, "versionDescriptor.versionType": "commit", "api-version": "7.1",
            }))
            if file.get("content") != content:
                raise ValueError("Existing draft branch content differs; do not mutate an earlier review.")
        return commit

    @staticmethod
    def files(draft: PreparedDraft) -> list[tuple[str, str]]:
        files = [(draft_path(draft.event_id), draft.content)]
        if draft.review_notes is not None:
            files.append((review_path(draft.event_id), draft.review_notes))
        return files

    def publish(self, draft: PreparedDraft) -> str:
        if content_hash(draft.content) != draft.content_sha256:
            raise ValueError("Prepared draft content hash does not match.")
        # Recover a previous successful publication after a lost response without
        # creating or editing another commit. This never force-pushes.
        existing = self.draft_commit(draft)
        if existing:
            return existing
        self.request("POST", "/pushes?api-version=7.1", {
            "refUpdates": [{"name": draft_branch(draft.event_id), "oldObjectId": "0" * 40}],
            "commits": [{
                "comment": f"Documentation draft for merged PR {draft.pull_request_id} ({draft.event_id})",
                "parents": [draft.source_commit],
                "changes": [
                    {"changeType": "add", "item": {"path": path},
                     "newContent": {"content": content, "contentType": "rawtext"}}
                    for path, content in self.files(draft)
                ],
            }],
        })
        readback = self.draft_commit(draft)
        if readback is None:
            raise ValueError("Draft push did not produce the expected ref; inspect before retry.")
        return readback
