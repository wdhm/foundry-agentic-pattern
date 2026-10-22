import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from documentation_agent.draft_reader import ToolboxDraftReader
from documentation_agent.settings import AssessmentSettings

from contracts.drafts import draft_path
from contracts.repositories import azure_file_uri, azure_repository

REPO = "https://dev.azure.com/test/project/_git/00000000-0000-4000-8000-000000000004"


@pytest.mark.parametrize("bad", [None, "uri", "path", "commit", "multiple", "empty", "tool"])
def test_official_toolbox_draft_reader_verifies_identity_before_returning_content(monkeypatch, bad):
    event = uuid4()
    commit = "b" * 40
    uri = azure_file_uri(azure_repository(REPO), draft_path(event), commit)
    if bad == "uri":
        uri = uri.replace("dev.azure.com", "attacker.example")
    elif bad == "path":
        uri = azure_file_uri(azure_repository(REPO), "/other.md", commit)
    elif bad == "commit":
        uri = azure_file_uri(azure_repository(REPO), draft_path(event), "c" * 40)
    documents = [{"uri": uri, "content": "# Exact draft\n\nContent.\n"}]
    if bad == "multiple":
        documents *= 2
    if bad == "empty":
        documents = []
    call = AsyncMock(return_value=json.dumps({"documents": documents}))
    events = []

    class Credential:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            events.append("credential-closed")

    class Toolbox:
        def __init__(self, credential, **kwargs):
            assert kwargs["allowed_tools"] == ["ado___repo_file"]
            assert kwargs["approval_mode"] == "never_require"
            self.functions = [SimpleNamespace(name="other" if bad == "tool" else "ado___repo_file")]
            self.call_tool = call

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            events.append("toolbox-closed")

    monkeypatch.setattr("documentation_agent.draft_reader.ManagedIdentityCredential", Credential)
    monkeypatch.setattr("documentation_agent.draft_reader.FoundryToolbox", Toolbox)
    settings = AssessmentSettings(
        project_endpoint="https://test.services.ai.azure.com/api/projects/test",
        toolbox_endpoint="https://test.services.ai.azure.com/api/projects/test/toolboxes/read/versions/2/mcp",
        model="test", model_version="test", ado_project="project", ado_wiki="wiki", ado_organization="test",
    )
    reader = ToolboxDraftReader(settings)
    if bad:
        with pytest.raises(ValueError):
            asyncio.run(reader(REPO, event, commit))
    else:
        assert asyncio.run(reader(REPO, event, commit)) == "# Exact draft\n\nContent.\n"
        call.assert_awaited_once_with(
            "ado___repo_file", action="get_content", repositoryId=azure_repository(REPO).repository, project="project",
            path=draft_path(event), version=commit, versionType="Commit",
        )
    assert events == ["toolbox-closed", "credential-closed"]
