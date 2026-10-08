import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from agent_framework import Content, Message, SupportsAgentRun
from agent_framework.exceptions import AgentInvalidRequestException
from documentation_agent import DocumentationAgent
from documentation_agent.main import create_server
from httpx import ASGITransport, AsyncClient

from contracts import CONTRACT_VERSION, AgentRequest, AgentResult, Subject


@pytest.fixture
def payload():
    return AgentRequest(
        contract_version=CONTRACT_VERSION,
        request_id=uuid4(),
        correlation_id=uuid4(),
        trigger="cli",
        requested_by="demo-reviewer",
        subject=Subject(repo="example/sample", commit_sha="a" * 40),
        documentation_standard_ref="data/documentation-standard.md",
    ).model_dump_json()


def test_stub_returns_typed_result(payload):
    agent = DocumentationAgent()
    assert isinstance(agent, SupportsAgentRun)
    response = asyncio.run(agent.run(payload))
    result = AgentResult.model_validate_json(response.text)
    assert result.request_id == AgentRequest.model_validate_json(payload).request_id
    assert result == response.value
    assert result.provenance.model == "not-invoked"


def test_stream_and_nonstream_match(payload):
    agent = DocumentationAgent()

    async def run():
        response = await agent.run(payload)
        stream = agent.run([Message("user", [payload])], stream=True)
        updates = [update async for update in stream]
        final = await stream.get_final_response()
        assert "".join(update.text for update in updates) == response.text
        assert final.value == response.value

    asyncio.run(run())


@pytest.mark.parametrize("payload", ["not JSON", "{}", "[]", '{"contract_version":"1.0.0"}'])
def test_invalid_contract_raises_explicit_error(payload):
    with pytest.raises(AgentInvalidRequestException, match="Invalid AgentRequest"):
        asyncio.run(DocumentationAgent().run(payload))


@pytest.mark.parametrize(
    "messages",
    [
        None,
        [],
        ["{}", "{}"],
        Message("assistant", ["{}"]),
        Message("user", [Content.from_text("{}"), Content.from_text("{}")]),
        Content.from_uri("https://example.com/image.png", media_type="image/png"),
    ],
)
def test_unsupported_message_shape_rejected(messages):
    with pytest.raises(AgentInvalidRequestException):
        asyncio.run(DocumentationAgent().run(messages))


def test_validation_error_does_not_echo_input():
    payload = json.dumps({"requested_by": {"secret": "do-not-echo"}})
    with pytest.raises(AgentInvalidRequestException) as exc:
        asyncio.run(DocumentationAgent().run(payload))
    assert "do-not-echo" not in str(exc.value)


def test_server_constructs():
    assert create_server() is not None


def test_example_matches_contract():
    path = Path(__file__).parents[2] / "src" / "agents" / "documentation-agent" / "examples" / "request.json"
    AgentRequest.model_validate_json(path.read_text(encoding="utf-8"))


def test_http_responses_transport(payload):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=create_server()), base_url="http://localhost") as client:
            response = await client.post("/responses", json={"input": payload, "stream": False, "store": False})
            response.raise_for_status()
            body = response.json()
            assert body["status"] == "completed"
            result = AgentResult.model_validate_json(body["output"][0]["content"][0]["text"])
            assert result.request_id == AgentRequest.model_validate_json(payload).request_id
            invalid = await client.post("/responses", json={"input": "{}", "stream": False, "store": False})
            invalid.raise_for_status()
            body = invalid.json()
            assert body["status"] == "failed"
            assert body["output"] == []
            assert "Invalid AgentRequest" in body["error"]["message"]

    asyncio.run(run())
