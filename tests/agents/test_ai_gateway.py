import asyncio
import json
import time
from pathlib import Path
from xml.etree import ElementTree

import httpx
import pytest
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import FoundryToolbox
from azure.ai.projects.aio import AIProjectClient
from azure.core.credentials import AccessToken
from documentation_agent.gateway import route_model_client
from documentation_agent.settings import AssessmentSettings
from openai import RateLimitError
from pydantic import ValidationError

ROOT = Path(__file__).parents[2]
MODEL_GATEWAY = "https://example.azure-api.net/documentation-model/"
TOOL_GATEWAY = "https://example.azure-api.net/documentation-tools/mcp?api-version=v1"


@pytest.fixture
def settings():
    return AssessmentSettings(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        toolbox_endpoint=(
            "https://example.services.ai.azure.com/api/projects/demo/toolboxes/reads/versions/1/mcp?api-version=v1"
        ),
        model="reviewed-model",
        model_version="2026-01-01",
        ado_project="demo",
        ado_wiki="demo.wiki",
    )


def test_environment_opt_in_is_independent_and_direct_by_default(settings):
    env = {
        "DOCUMENTATION_PROJECT_ENDPOINT": settings.project_endpoint,
        "TOOLBOX_ENDPOINT": settings.toolbox_endpoint,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": settings.model,
        "DOCUMENTATION_MODEL_VERSION": settings.model_version,
        "DOCUMENTATION_ADO_PROJECT": settings.ado_project,
        "DOCUMENTATION_ADO_WIKI": settings.ado_wiki,
    }
    direct = AssessmentSettings.from_environment(env)
    assert direct.model_gateway_endpoint is direct.toolbox_gateway_endpoint is None
    env["DOCUMENTATION_MODEL_GATEWAY_ENDPOINT"] = MODEL_GATEWAY
    assert AssessmentSettings.from_environment(env).toolbox_gateway_endpoint is None
    env["DOCUMENTATION_TOOLBOX_GATEWAY_ENDPOINT"] = TOOL_GATEWAY
    routed = AssessmentSettings.from_environment(env)
    assert routed.model_gateway_endpoint == MODEL_GATEWAY
    assert routed.toolbox_gateway_endpoint == TOOL_GATEWAY
    assert routed.project_endpoint == settings.project_endpoint
    assert routed.toolbox_endpoint == settings.toolbox_endpoint
    assert routed.model_version == settings.model_version


@pytest.mark.parametrize("field,value", [
    ("model_gateway_endpoint", ""),
    ("model_gateway_endpoint", "http://example/documentation-model/"),
    ("model_gateway_endpoint", "https://user:secret@example/documentation-model/"),
    ("model_gateway_endpoint", MODEL_GATEWAY + "?api-key=secret"),
    ("model_gateway_endpoint", MODEL_GATEWAY + "#fragment"),
    ("model_gateway_endpoint", "https://example:8443/documentation-model/"),
    ("model_gateway_endpoint", "https://example/documentation-model"),
    ("toolbox_gateway_endpoint", "https://example/documentation-tools/mcp"),
    ("toolbox_gateway_endpoint", TOOL_GATEWAY + "&key=secret"),
    ("toolbox_gateway_endpoint", "https://example/write-tools/mcp?api-version=v1"),
])
def test_invalid_gateway_configuration_fails_closed(settings, field, value):
    with pytest.raises(ValidationError):
        AssessmentSettings.model_validate({**settings.model_dump(), field: value})


@pytest.mark.parametrize("gateway_enabled", [False, True])
@pytest.mark.parametrize("mode", ["json", "stream", "throttled"])
def test_actual_foundry_sdk_routes_without_changing_auth_or_payload(settings, monkeypatch, gateway_enabled, mode):
    seen = []
    scopes = []
    if gateway_enabled:
        settings.model_gateway_endpoint = MODEL_GATEWAY

    class Credential:
        async def get_token(self, *requested_scopes, **kwargs):
            scopes.extend(requested_scopes)
            return AccessToken("test-token-not-a-credential", int(time.time()) + 3600)

    def handler(request):
        seen.append(request)
        if mode == "throttled":
            return httpx.Response(429, json={"error": {"message": "limit", "type": "rate_limit"}})
        if mode == "stream":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    'data: {"type":"response.output_text.delta","delta":"kept"}\n\n'
                    'data: {"type":"response.completed","response":{"id":"resp_1","status":"completed"}}\n\n'
                    'data: [DONE]\n\n'
                ),
            )
        return httpx.Response(200, json={"id": "resp_1", "object": "response", "output": [], "status": "completed"})

    async def run():
        async with AIProjectClient(endpoint=settings.project_endpoint, credential=Credential()) as project:
            original = project.get_openai_client
            monkeypatch.setattr(
                project, "get_openai_client",
                lambda **kwargs: original(
                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs,
                ),
            )
            client = FoundryChatClient(project_client=project, model=settings.model)
            original_url = str(client.client.base_url)
            original_retries = client.client.max_retries
            route_model_client(client, settings)
            assert str(client.client.base_url) == (MODEL_GATEWAY if gateway_enabled else original_url)
            assert client.client.max_retries == (0 if gateway_enabled else original_retries)
            async with client.client:
                if mode == "throttled":
                    # Keep the direct-mode comparison fast; production direct retries are unchanged above.
                    client.client.max_retries = 0
                    with pytest.raises(RateLimitError):
                        await client.client.responses.create(model=settings.model, input="unchanged", store=False)
                else:
                    result = await client.client.responses.create(
                        model=settings.model, input="unchanged", store=False, stream=mode == "stream",
                    )
                    if mode == "stream":
                        assert [event.type async for event in result] == [
                            "response.output_text.delta", "response.completed",
                        ]
                    else:
                        assert result.id == "resp_1"

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert len(seen) == 1
    expected = MODEL_GATEWAY if gateway_enabled else settings.project_endpoint + "/openai/v1/"
    assert str(seen[0].url).split("?")[0] == expected + "responses"
    assert seen[0].headers["Authorization"] == "Bearer test-token-not-a-credential"
    assert set(scopes) == {"https://ai.azure.com/.default"}
    body = json.loads(seen[0].content)
    assert body["model"] == settings.model
    assert body["input"] == "unchanged"
    assert body["store"] is False


def test_actual_toolbox_mcp_session_keeps_auth_and_lifecycle_headers(monkeypatch):
    seen = []
    scopes = []

    class Credential:
        async def get_token(self, *requested_scopes, **kwargs):
            scopes.extend(requested_scopes)
            return AccessToken("test-token-not-a-credential", int(time.time()) + 3600)

    def handler(request):
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(405)
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "offline-read-toolbox", "version": "1"},
            }
        elif body["method"] == "tools/list":
            result = {"tools": [{
                "name": "ado___wiki",
                "inputSchema": {"type": "object", "properties": {"action": {"type": "string"}}},
            }]}
        elif body["method"] == "ping":
            result = {}
        elif body["method"] == "tools/call":
            assert body["params"] == {"name": "ado___wiki", "arguments": {"action": "get_page"}}
            result = {"content": [{"type": "text", "text": "exact source"}], "isError": False}
        else:
            pytest.fail(f"Unexpected MCP method: {body['method']}")
        return httpx.Response(
            200, headers={"mcp-session-id": "session-fixed", "content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": body["id"], "result": result},
        )

    class OfflineClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(
        "agent_framework_foundry_hosting._toolbox.httpx.AsyncClient",
        OfflineClient,
    )

    async def run():
        async with FoundryToolbox(
            Credential(), url=TOOL_GATEWAY, name="reviewed-reads",
            allowed_tools=["ado___wiki"], tool_name_prefix="", approval_mode="never_require",
        ) as toolbox:
            assert [function.name for function in toolbox.functions] == ["ado___wiki"]
            result = await toolbox.call_tool("ado___wiki", action="get_page")
            assert [content.text for content in result] == ["exact source"]

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert set(scopes) == {"https://ai.azure.com/.default"}
    assert {request.method for request in seen} == {"POST", "GET", "DELETE"}
    for request in seen:
        assert str(request.url) == TOOL_GATEWAY
        assert request.headers["authorization"] == "Bearer test-token-not-a-credential"
        if request.method != "POST" or json.loads(request.content)["method"] != "initialize":
            assert request.headers["mcp-session-id"] == "session-fixed"
            assert request.headers["mcp-protocol-version"] == "2025-06-18"


@pytest.mark.parametrize("filename", ["model-policy.xml", "tool-policy.xml"])
def test_policy_contract_is_identity_bound_nonreplaying_and_stream_safe(filename):
    policy = ElementTree.parse(ROOT / "infra" / "ai-gateway" / filename).getroot()
    auth = policy.find("inbound/validate-jwt")
    assert auth.attrib["header-name"] == "Authorization"
    assert auth.findtext("audiences/audience") == "https://ai.azure.com"
    assert {claim.attrib["name"] for claim in auth.findall("required-claims/claim")} == {"tid", "oid"}
    forward = policy.find("backend/forward-request")
    assert forward.attrib["buffer-response"] == "false"
    assert forward.attrib["buffer-request-body"] == "false"
    forbidden = {"retry", "cache-lookup", "cache-store", "authentication-managed-identity", "set-body", "base"}
    assert not forbidden.intersection(element.tag for element in policy.iter())
    assert not any(
        element.tag == "set-header" and element.attrib.get("name") == "Authorization" for element in policy.iter()
    )
    assert "context.Response.Body" not in ElementTree.tostring(policy).decode()
    if filename == "model-policy.xml":
        limit = policy.find("inbound/llm-token-limit")
        assert limit.attrib["token-quota-period"] == "Daily"
        assert limit.attrib["estimate-prompt-tokens"] == "false"
        assert policy.find("inbound/validate-content") is not None
    else:
        assert policy.find("inbound/rate-limit-by-key").attrib["renewal-period"] == "60"
        assert policy.findtext("inbound/set-query-parameter/value") == "v1"
