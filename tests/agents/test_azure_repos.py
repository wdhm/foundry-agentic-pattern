import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from agent_framework import Content, FunctionInvocationContext, FunctionTool, MiddlewareFailure
from documentation_agent.assessment import AssessmentAgent
from documentation_agent.read_policy import READ_TOOLS, ReadOnlyPolicy, parse_read_result, read_tools, require_read
from documentation_agent.settings import AssessmentSettings
from mcp.types import CallToolResult, EmbeddedResource, TextResourceContents

from contracts.evidence import source_records, trace_evidence_problems
from contracts.repositories import AzureRepository, azure_file_uri, azure_repository
from contracts.v1 import AgentRequest

REPOSITORY = AzureRepository("example-org", "demo-project", "example-repository")
COMMIT = "a" * 40
URI = azure_file_uri(REPOSITORY, "/config/settings.json", COMMIT)
FILE = '{"retry": {"maxAttempts": 3, "delaySeconds": 5}}'


@pytest.fixture
def settings():
    return AssessmentSettings(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        toolbox_endpoint="https://example.services.ai.azure.com/api/projects/demo/toolboxes/reads/versions/2/mcp",
        model="example-model", model_version="example-version", ado_project="demo-project",
        ado_wiki="demo-project.wiki", ado_organization="example-org",
    )


@pytest.fixture
def request_v1():
    return AgentRequest.model_validate({
        "contract_version": "1.0.0", "request_id": str(uuid4()), "correlation_id": str(uuid4()),
        "trigger": "cli", "requested_by": "demo-reviewer",
        "subject": {
            "repo": "https://dev.azure.com/example-org/demo-project/_git/example-repository",
            "commit_sha": COMMIT, "changed_paths": ["config/settings.json"],
        },
        "documentation_standard_ref": "DS-14",
    })


def arguments():
    return {
        "action": "get_content", "project": "demo-project", "repositoryId": "example-repository",
        "path": "/config/settings.json", "version": COMMIT, "versionType": "Commit",
    }


def file_output(uri=URI):
    return parse_read_result(CallToolResult(content=[
        EmbeddedResource(type="resource", resource=TextResourceContents(
            uri=uri, mimeType="text/plain", text=FILE,
        )),
    ]))


def test_azure_repos_requires_operator_opt_in(settings, request_v1):
    disabled = settings.model_copy(update={"ado_organization": None})
    assert read_tools(disabled) == READ_TOOLS
    with pytest.raises(MiddlewareFailure, match="not allowed"):
        require_read("ado___repo_file", arguments(), request_v1, disabled)
    assert read_tools(settings) == (*READ_TOOLS, "ado___repo_file")
    require_read("ado___repo_file", arguments(), request_v1, settings)


@pytest.mark.parametrize(("key", "value"), [
    ("action", "update"), ("action", "list_directory"), ("project", "other-project"),
    ("repositoryId", "other-repository"), ("version", "main"), ("version", "b" * 40),
    ("versionType", "Branch"), ("versionType", "Tag"), ("path", "../secret"),
    ("path", "/../secret"), ("path", "/config//secret"), ("path", "/config/%2e%2e/secret"),
    ("path", "/config\\secret"), ("path", "/"), ("path", None),
])
def test_invalid_azure_reads_fail_before_dispatch(settings, request_v1, key, value):
    args = arguments()
    args[key] = value
    with pytest.raises(MiddlewareFailure):
        require_read("ado___repo_file", args, request_v1, settings)


@pytest.mark.parametrize("repo", [
    "https://dev.azure.com/other-org/demo-project/_git/example-repository",
    "https://dev.azure.com/example-org/other-project/_git/example-repository",
    "https://dev.azure.com.evil/example-org/demo-project/_git/example-repository",
    "https://dev.azure.com/example-org/demo-project/_git/../example-repository",
    "https://dev.azure.com/example-org/demo-project/_git/repo%2fother",
    "https://dev.azure.com/example-org/demo-project/_git/example-repository?ref=main",
    "https://user@dev.azure.com/example-org/demo-project/_git/example-repository",
    "example/repository",
])
def test_repository_boundary_is_enforced(settings, request_v1, repo):
    changed = request_v1.model_copy(update={"subject": request_v1.subject.model_copy(update={"repo": repo})})
    with pytest.raises(MiddlewareFailure):
        require_read("ado___repo_file", arguments(), changed, settings)


def test_live_embedded_resource_shape_yields_commit_pinned_evidence():
    call = {
        "type": "mcp_call", "status": "completed", "server_label": "ado", "name": "repo_file",
        "arguments": json.dumps(arguments()), "output": file_output(),
    }
    raw = {"output": [
        {"type": "mcp_call", "status": "completed", "server_label": "knowledge",
         "name": "knowledge_base_retrieve"},
        call,
    ]}
    result = {"evidence": [{"id": "G1", "source": "git", "version": COMMIT, "uri": URI, "excerpt": FILE}]}
    assert source_records(raw) == [{"source": "git", "version": COMMIT, "uris": [URI], "content": FILE}]
    assert trace_evidence_problems(raw, result) == []
    call["arguments"] = json.dumps({**arguments(), "versionType": "Branch"})
    assert trace_evidence_problems(raw, result)


@pytest.mark.parametrize("uri", [
    URI.replace("versionType=Commit", "versionType=Branch"),
    URI.replace(COMMIT, "b" * 40),
    URI.replace("example-org", "other-org"),
    URI.replace("example-repository", "other-repository"),
    URI + "&versionDescriptor.version=main",
    URI.replace("dev.azure.com", "dev.azure.com.evil"),
])
def test_mismatched_file_resource_is_not_recorded(settings, request_v1, uri):
    guard = ReadOnlyPolicy(request_v1, settings)
    context = FunctionInvocationContext(FunctionTool(name="ado___repo_file"), arguments=arguments())

    async def dispatch():
        context.result = [Content.from_text(file_output(uri))]

    with pytest.raises(MiddlewareFailure, match="commit-pinned"):
        asyncio.run(guard.process(context, dispatch))
    assert guard.calls == []


def test_azure_repos_assessment_preserves_the_normal_result_contract(settings, request_v1):
    class Runner:
        async def analyze(self, request, instructions, guard):
            assert "ado___repo_file action=get_content" in instructions
            for name, args, output in [
                ("knowledge___knowledge_base_retrieve", {}, '{"rules": "DS-14"}'),
                ("ado___repo_file", arguments(), file_output()),
            ]:
                context = FunctionInvocationContext(FunctionTool(name=name), arguments=args)

                async def dispatch(context=context, output=output):
                    context.result = [Content.from_text(output)]

                await guard.process(context, dispatch)
            return json.dumps({
                "documentation_status": "up_to_date", "findings": [], "proposed_changes": [],
                "missing_information": [], "requires_human_review": False, "confidence": 0.8,
                "evidence": [{"id": "G1", "source": "git", "uri": URI, "version": COMMIT, "excerpt": FILE}],
            })

    result = asyncio.run(AssessmentAgent(settings, Runner()).assess(request_v1))
    assert result.request_id == request_v1.request_id
    assert result.evidence[0].uri == URI


def test_example_request_uses_a_pinned_azure_repository():
    example = Path("src/agents/documentation-agent/examples/azure-repos-request.json")
    request = AgentRequest.model_validate_json(example.read_text())
    assert azure_repository(request.subject.repo).organization == "foundry-agentic"
    assert request.subject.commit_sha == "8c9ad675df1b05ffa77babd1b0e0ba0647f7bcb2"
