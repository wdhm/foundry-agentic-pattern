"""Read a published draft at its exact commit through the existing read Toolbox."""

import asyncio
import json
from uuid import UUID

from agent_framework_foundry_hosting import FoundryToolbox
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

from contracts.drafts import draft_path, review_path
from contracts.repositories import azure_repository, matches_azure_file

from .read_policy import parse_read_result
from .settings import AssessmentSettings


class ToolboxDraftReader:
    def __init__(self, settings: AssessmentSettings) -> None:
        self.settings = settings

    async def __call__(self, repository_url: str, event_id: UUID, commit: str) -> str:
        return await self.read(repository_url, draft_path(event_id), commit)

    async def read_notes(self, repository_url: str, event_id: UUID, commit: str) -> str:
        return await self.read(repository_url, review_path(event_id), commit)

    async def read(self, repository_url: str, path: str, commit: str) -> str:
        repo = azure_repository(repository_url)
        if repo.organization != self.settings.ado_organization or repo.project != self.settings.ado_project:
            raise ValueError("Draft must belong to the configured Azure Repos project.")
        credential = AzureCliCredential() if self.settings.auth_mode == "azure_cli" else ManagedIdentityCredential()
        async with (
            asyncio.timeout(self.settings.timeout_seconds),
            credential,
            FoundryToolbox(
                credential, url=self.settings.toolbox_endpoint, allowed_tools=["ado___repo_file"],
                tool_name_prefix="", approval_mode="never_require", parse_tool_results=parse_read_result,
            ) as toolbox,
        ):
            if {tool.name for tool in toolbox.functions} != {"ado___repo_file"}:
                raise ValueError("Read Toolbox does not expose the required draft file reader.")
            output = await toolbox.call_tool(
                "ado___repo_file", action="get_content", repositoryId=repo.repository, project=repo.project,
                path=path, version=commit, versionType="Commit",
            )
            if not isinstance(output, str):
                raise ValueError("Unexpected draft read result.")
            payload = json.loads(output)
            docs = payload.get("documents") if isinstance(payload, dict) else None
            if not isinstance(docs, list) or len(docs) != 1:
                raise ValueError("Expected exactly one pinned draft document.")
            doc = docs[0]
            if (
                not isinstance(doc, dict) or not isinstance(doc.get("content"), str)
                or not isinstance(doc.get("uri"), str)
                or not matches_azure_file(doc["uri"], repo, path, commit)
            ):
                raise ValueError("Draft read does not match the requested repository, path and commit.")
            content = doc["content"]
            if not isinstance(content, str):
                raise ValueError("Draft content is not text.")
            return content
