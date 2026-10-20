import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agent_framework import AgentSession, Content, Message
from agent_framework.exceptions import AgentInvalidRequestException
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.core.storage import FoundryStateStore
from documentation_agent.approval import (
    COMMAND,
    STORE_NAME,
    FoundryToolConnection,
    PendingCall,
    ToolApprovalAgent,
    ToolApprovalPolicy,
    connect_tool,
)
from documentation_agent.main import create_server
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator
from mcp.types import CallToolResult, ListToolsResult, Tool, ToolExecution


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT", raising=False)


@pytest.fixture
def policy():
    return ToolApprovalPolicy(
        toolbox_endpoint="https://test.services.ai.azure.com/api/projects/test/toolboxes/test-write/versions/1/mcp"
        "?api-version=v1",
        tool_name="ado___test_write",
        fixed_arguments={"project": "test", "wiki": "test.wiki", "path": "/disposable"},
        content_parameter="content",
    )


@pytest.fixture
def spec(policy):
    return Tool(
        name=policy.tool_name,
        description="Fictional test schema; not a claim about the P2 tool.",
        inputSchema={
            "type": "object",
            "properties": {key: {"type": "string"} for key in ("project", "wiki", "path", "content")},
            "required": ["project", "wiki", "path", "content"],
            "additionalProperties": False,
        },
        _meta={"test-metadata": "preserve"},
    )


@pytest.fixture
def proposal():
    return {
        "action": "propose",
        "run_id": str(uuid4()),
        "content": "Proposed test content.",
        "evidence": [
            {
                "id": "test",
                "source": "git",
                "uri": "https://example.com/test",
                "version": "a" * 40,
                "excerpt": "Test source excerpt.",
            }
        ],
    }


@pytest.fixture
def result_command(proposal):
    return {
        "action": "propose_result",
        "proposal_index": 0,
        "result": {
            "contract_version": "1.0.0",
            "request_id": proposal["run_id"],
            "documentation_status": "gaps_found",
            "findings": [
                {"category": "operations", "severity": "medium", "description": "Missing", "evidence_refs": ["test"]}
            ],
            "proposed_changes": [
                {
                    "target_page": "/disposable",
                    "target_section": "Operations",
                    "proposed_content": proposal["content"],
                    "evidence_refs": ["test"],
                }
            ],
            "missing_information": [],
            "evidence": proposal["evidence"],
            "confidence": 0.8,
            "requires_human_review": True,
            "provenance": {
                "agent_name": "documentation-agent",
                "agent_version": "0.4.0",
                "model": "offline-test",
                "model_version": "test",
                "prompt_version": "test",
                "policy_version": "test",
                "contract_version": "1.0.0",
            },
        },
    }


@pytest.fixture
def harness(policy, spec):
    session = AsyncMock()
    session.call_tool.return_value = CallToolResult(content=[], structuredContent={"written": True})
    connection = FoundryToolConnection(session, spec)

    @asynccontextmanager
    async def connector(_):
        yield connection

    return ToolApprovalAgent(policy, connector=connector, allow_local=True), session, connection


async def propose(agent, session, command):
    response = await agent.run(json.dumps(command), session=session)
    return next(content for content in response.messages[0].contents if content.type == "function_approval_request")


async def inspect(agent, session, approval_id):
    response = await agent.run(json.dumps({"action": "inspect", "pending_id": approval_id}), session=session)
    return json.loads(response.text)


def decision(approval, approve=True):
    return Message("user", [approval.to_function_approval_response(approve)])


def test_pending_then_exact_call_only_once_with_native_decision(harness, proposal, policy):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        before = await inspect(agent, session, approval.id)
        assert before["status"] == "pending"
        assert before["result"] is None
        remote.call_tool.assert_not_called()
        result = json.loads((await agent.run(decision(approval), session=session)).text)
        assert result["status"] == "succeeded"
        assert result["decided_by"] == "local-unverified"
        assert result["run_id"] == proposal["run_id"]
        assert result["result"]["structuredContent"] == {"written": True}
        remote.call_tool.assert_awaited_once_with(
            policy.tool_name,
            arguments=policy.arguments(proposal["content"]),
            meta={"test-metadata": "preserve"},
        )
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(decision(approval), session=session)
        assert await inspect(agent, session, approval.id) == result

    asyncio.run(run())


def test_reject_no_call_or_later_approval(harness, proposal):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        await agent.run(decision(approval, False), session=session)
        assert (await inspect(agent, session, approval.id))["status"] == "rejected"
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(decision(approval), session=session)
        remote.call_tool.assert_not_called()

    asyncio.run(run())


def test_modify_requires_fresh_approval_preserving_target_and_run(harness, proposal, policy):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        old = await propose(agent, session, proposal)
        changed = await agent.run(
            json.dumps({"action": "modify", "pending_id": old.id, "feedback": "Reword", "content": "Revised text"}),
            session=session,
        )
        new = next(c for c in changed.messages[0].contents if c.type == "function_approval_request")
        record = await inspect(agent, session, old.id)
        assert record["status"] == "modified"
        assert record["replacement_id"] == new.id
        assert record["feedback"] == "Reword"
        assert old.id != new.id
        remote.call_tool.assert_not_called()
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(decision(old), session=session)
        await agent.run(decision(new), session=session)
        remote.call_tool.assert_awaited_once()
        assert remote.call_tool.call_args.kwargs["arguments"] == policy.arguments("Revised text")
        assert (await inspect(agent, session, new.id))["run_id"] == proposal["run_id"]

    asyncio.run(run())


@pytest.mark.parametrize("change", ["tool", "call_id", "content", "target", "pending_id"])
def test_decision_tamper_never_dispatches(harness, proposal, change):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        altered = Content.from_dict(approval.to_function_approval_response(True).to_dict())
        if change == "tool":
            altered.function_call.name = "ado___arbitrary"
        elif change == "call_id":
            altered.function_call.call_id = str(uuid4())
        elif change == "pending_id":
            altered.id = str(uuid4())
        else:
            args = dict(altered.function_call.arguments)
            args["content" if change == "content" else "path"] = "unauthorized"
            altered.function_call.arguments = args
        with pytest.raises(ValueError):
            await agent.run(Message("user", [altered]), session=session)
        remote.call_tool.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["tool_schema", "metadata", "policy", "hash", "expired", "owner", "session"])
def test_changed_binding_or_expired_approval_never_dispatches(harness, proposal, change):
    async def run():
        agent, remote, connection = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        if change == "tool_schema":
            connection.spec.inputSchema["description"] = "new schema"
        elif change == "metadata":
            connection.spec.meta = {"changed": True}
        elif change == "policy":
            agent.policy.fixed_arguments["path"] = "/different"
        elif change == "session":
            session = agent.create_session()
        else:
            store = await FoundryStateStore.get_or_create(STORE_NAME, user_isolation=True)
            async with store:
                item = await store.get_item(approval.id)
                record = dict(item.value)
                if change == "hash":
                    record["args_hash"] = "tampered"
                elif change == "owner":
                    record["owner"] = "someone-else"
                else:
                    record["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
                await store.set_item(approval.id, record, if_match=item.etag)
        with pytest.raises(ValueError):
            await agent.run(decision(approval), session=session)
        remote.call_tool.assert_not_called()

    asyncio.run(run())


def test_competing_approvals_claim_before_external_dispatch(harness, proposal):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)

        async def write(*args, **kwargs):
            assert (await inspect(agent, session, approval.id))["status"] == "executing"
            await asyncio.sleep(0)
            return CallToolResult(content=[])

        remote.call_tool.side_effect = write
        outcomes = await asyncio.gather(
            agent.run(decision(approval), session=session),
            agent.run(decision(approval), session=session),
            return_exceptions=True,
        )
        assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
        remote.call_tool.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["connection", "mcp_error", "cancelled", "timeout"])
def test_uncertain_external_outcome_never_retried(harness, proposal, failure):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        if failure == "mcp_error":
            remote.call_tool.return_value = CallToolResult(content=[], isError=True)
            expected = RuntimeError
        elif failure == "cancelled":
            remote.call_tool.side_effect = asyncio.CancelledError
            expected = asyncio.CancelledError
        elif failure == "timeout":
            remote.call_tool.side_effect = TimeoutError
            expected = TimeoutError
        else:
            from anyio import ClosedResourceError

            remote.call_tool.side_effect = ClosedResourceError
            expected = ClosedResourceError
        with pytest.raises(expected):
            await agent.run(decision(approval), session=session)
        assert (await inspect(agent, session, approval.id))["status"] == "outcome_unknown"
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(decision(approval), session=session)
        remote.call_tool.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("failed_state", ["executing", "succeeded", "all_after_claim"])
def test_storage_failure_does_not_allow_dispatch_or_retry(harness, proposal, monkeypatch, failed_state):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        original = FoundryStateStore.set_item

        async def store_write(self, key, value, **kwargs):
            if value["status"] == failed_state or (
                failed_state == "all_after_claim" and value["status"] in {"succeeded", "outcome_unknown"}
            ):
                raise ConnectionError("state unavailable")
            return await original(self, key, value, **kwargs)

        monkeypatch.setattr(FoundryStateStore, "set_item", store_write)
        with pytest.raises(ConnectionError):
            await agent.run(decision(approval), session=session)
        record = await inspect(agent, session, approval.id)
        if failed_state == "executing":
            remote.call_tool.assert_not_called()
            assert record["status"] == "pending"
        else:
            assert record["status"] == ("executing" if failed_state == "all_after_claim" else "outcome_unknown")
            with pytest.raises(ValueError, match="no longer pending"):
                await agent.run(decision(approval), session=session)
            remote.call_tool.assert_awaited_once()

    asyncio.run(run())


def test_restart_retains_claim_not_only_response_history(harness, proposal):
    async def run():
        agent, remote, _ = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        restored = AgentSession.from_dict(session.to_dict())
        restarted = ToolApprovalAgent(agent.policy, connector=agent.connector, allow_local=True)
        await restarted.run(decision(approval), session=restored)
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(decision(approval), session=session)
        remote.call_tool.assert_awaited_once()

    asyncio.run(run())


def test_modify_invalidates_old_call_even_when_new_discovery_fails(harness, proposal, monkeypatch):
    async def run():
        agent, remote, connection = harness
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        connection.spec.inputSchema = {"type": "object", "properties": {}}
        with pytest.raises(ValueError):
            await agent.run(
                json.dumps({"action": "modify", "pending_id": approval.id, "feedback": "Change", "content": "New"}),
                session=session,
            )
        assert (await inspect(agent, session, approval.id))["status"] == "modified"
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(decision(approval), session=session)
        remote.call_tool.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["target", "approve_text", "non_user", "mixed", "schema", "remote_ref"])
def test_invalid_request_cannot_bypass_approval(harness, proposal, invalid):
    async def run():
        agent, remote, connection = harness
        session = agent.create_session()
        bad = deepcopy(proposal)
        if invalid == "target":
            bad["arguments"] = {"path": "/real-page"}
        if invalid == "schema":
            connection.spec.inputSchema["properties"]["content"] = {"type": "integer"}
        if invalid == "remote_ref":
            connection.spec.inputSchema["properties"]["content"] = {"$ref": "https://example.com/schema"}
        message = json.dumps(bad)
        if invalid == "approve_text":
            message = "approve"
        if invalid == "non_user":
            message = Message("assistant", [message])
        if invalid == "mixed":
            approval = await propose(agent, session, proposal)
            message = Message("user", [approval.to_function_approval_response(True), Content.from_text("extra")])
        with pytest.raises((ValueError, AgentInvalidRequestException)):
            await agent.run(message, session=session)
        remote.call_tool.assert_not_called()

    asyncio.run(run())


def test_native_http_approval_replay_and_stream(harness, proposal):
    async def run():
        agent, remote, _ = harness
        server = ResponsesHostServer(agent, history_source="agent")
        async with AsyncClient(transport=ASGITransport(app=server), base_url="http://localhost") as client:
            first = (await client.post("/responses", json={"input": json.dumps(proposal), "stream": False})).json()
            assert first["status"] == "completed", first
            pending = next(item for item in first["output"] if item["type"] == "mcp_approval_request")
            remote.call_tool.assert_not_called()
            body = {
                "input": [{"type": "mcp_approval_response", "approval_request_id": pending["id"], "approve": True}],
                "previous_response_id": first["id"],
                "stream": False,
            }
            approved = (await client.post("/responses", json=body)).json()
            assert approved["status"] == "completed", approved
            text = next(p["text"] for i in approved["output"] if i["type"] == "message" for p in i["content"])
            assert json.loads(text)["status"] == "succeeded"
            replay = (await client.post("/responses", json={**body, "stream": True})).text
            assert '"status":"failed"' in replay or '"status": "failed"' in replay
            remote.call_tool.assert_awaited_once()

    asyncio.run(run())


def test_actor_and_mode_require_explicit_authorization(policy, proposal, monkeypatch):
    agent = ToolApprovalAgent(policy)
    with pytest.raises(ValueError, match="Verified platform user"):
        asyncio.run(agent.run(json.dumps(proposal), session=agent.create_session()))
    monkeypatch.setenv("DOCUMENTATION_MODE", "approval")
    monkeypatch.delenv("DOCUMENTATION_ENABLE_APPROVAL", raising=False)
    with pytest.raises(ValueError, match="explicit"):
        create_server()
    monkeypatch.setenv("DOCUMENTATION_ENABLE_APPROVAL", "true")
    monkeypatch.delenv("DOCUMENTATION_APPROVAL_POLICY", raising=False)
    with pytest.raises(ValueError, match="reviewed JSON"):
        create_server()


def test_native_http_modify_reject_and_stale_approval(harness, proposal):
    async def run():
        agent, remote, _ = harness
        server = ResponsesHostServer(agent, history_source="agent")
        async with AsyncClient(transport=ASGITransport(app=server), base_url="http://localhost") as client:
            first = (await client.post("/responses", json={"input": json.dumps(proposal), "stream": False})).json()
            assert first["status"] == "completed", first
            pending = next(item for item in first["output"] if item["type"] == "mcp_approval_request")
            text = next(p["text"] for i in first["output"] if i["type"] == "message" for p in i["content"])
            pending_id = text.splitlines()[0].removeprefix("Pending ID: ")
            modified = (
                await client.post(
                    "/responses",
                    json={
                        "previous_response_id": first["id"],
                        "stream": False,
                        "input": json.dumps(
                            {"action": "modify", "pending_id": pending_id, "feedback": "Reword", "content": "New"}
                        ),
                    },
                )
            ).json()
            assert modified["status"] == "completed", modified
            new = next(item for item in modified["output"] if item["type"] == "mcp_approval_request")
            for previous, approval_id, approved, expected in [
                (first["id"], pending["id"], True, "failed"),
                (modified["id"], new["id"], False, "completed"),
                (modified["id"], new["id"], True, "failed"),
            ]:
                result = (
                    await client.post(
                        "/responses",
                        json={
                            "previous_response_id": previous,
                            "stream": False,
                            "input": [
                                {
                                    "type": "mcp_approval_response",
                                    "approval_request_id": approval_id,
                                    "approve": approved,
                                }
                            ],
                        },
                    )
                ).json()
                assert result["status"] == expected, result
            remote.call_tool.assert_not_called()

    asyncio.run(run())


def test_actual_timeout_preserves_non_retryable_claim(harness, proposal):
    async def run():
        agent, remote, _ = harness
        agent.policy.timeout_seconds = 1
        session = agent.create_session()
        approval = await propose(agent, session, proposal)

        async def wait_forever(*args, **kwargs):
            await asyncio.Event().wait()

        remote.call_tool.side_effect = wait_forever
        with pytest.raises(TimeoutError):
            await agent.run(decision(approval), session=session)
        assert (await inspect(agent, session, approval.id))["status"] == "outcome_unknown"
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(decision(approval), session=session)
        remote.call_tool.assert_awaited_once()

    asyncio.run(run())


def test_hosted_mode_never_uses_local_identity_or_cli_credentials(policy, monkeypatch):
    from azure.ai.agentserver.core import FoundryAgentRequestContext

    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
    monkeypatch.setattr(
        "documentation_agent.approval_common.get_request_context", lambda: FoundryAgentRequestContext()
    )
    with pytest.raises(ValueError, match="Verified platform user"):
        ToolApprovalAgent(policy, allow_local=True).actor()
    policy.auth_mode = "azure_cli"

    async def run():
        async with connect_tool(policy):
            pytest.fail("Must not connect with operator credentials in hosted mode.")

    with pytest.raises(ValueError, match="managed identity"):
        asyncio.run(run())


def test_storage_create_failure_does_not_emit_approval_or_dispatch(harness, proposal, monkeypatch):
    async def run():
        agent, remote, _ = harness
        monkeypatch.setattr(FoundryStateStore, "create_item", AsyncMock(side_effect=ConnectionError("unavailable")))
        with pytest.raises(ConnectionError):
            await propose(agent, agent.create_session(), proposal)
        remote.call_tool.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://test.services.ai.azure.com/api/projects/test/toolboxes/test/versions/1/mcp?api-version=v1",
        "https://evil.example/api/projects/test/toolboxes/test/versions/1/mcp?api-version=v1",
        "https://test.services.ai.azure.com/api/projects/test/toolboxes/test/mcp?api-version=v1",
    ],
)
def test_policy_rejects_unpinned_or_untrusted_endpoints(policy, endpoint):
    with pytest.raises(ValueError, match="versioned Foundry"):
        ToolApprovalPolicy.model_validate({**policy.model_dump(), "toolbox_endpoint": endpoint})


@pytest.mark.parametrize("inventory", ["valid", "missing", "duplicate", "task", "loop"])
def test_official_connector_discovery_is_filtered_paginated_and_closed(policy, spec, monkeypatch, inventory):
    remote = AsyncMock()
    second = [spec] if inventory != "missing" else []
    if inventory == "duplicate":
        second.append(spec)
    if inventory == "task":
        spec.execution = ToolExecution(taskSupport="required")
    remote.list_tools.side_effect = [
        ListToolsResult(tools=[], nextCursor="page2"),
        ListToolsResult(tools=second, nextCursor="page2" if inventory == "loop" else None),
    ]
    events = []

    class Credential:
        async def __aenter__(self):
            events.append("credential-open")
            return self

        async def __aexit__(self, *args):
            events.append("credential-close")

    class Toolbox:
        def __init__(self, credential, **kwargs):
            assert kwargs["approval_mode"] == "always_require"
            assert kwargs["allowed_tools"] == [policy.tool_name]
            assert kwargs["load_tools"] is False
            self.session = remote

        async def __aenter__(self):
            events.append("toolbox-open")
            return self

        async def __aexit__(self, *args):
            events.append("toolbox-close")

    monkeypatch.setattr("documentation_agent.approval.ManagedIdentityCredential", Credential)
    monkeypatch.setattr("documentation_agent.approval.FoundryToolbox", Toolbox)

    async def run():
        async with connect_tool(policy) as connection:
            assert connection.spec.name == policy.tool_name

    if inventory == "valid":
        asyncio.run(run())
    else:
        with pytest.raises(ValueError):
            asyncio.run(run())
    assert events == ["credential-open", "toolbox-open", "toolbox-close", "credential-close"]
    remote.call_tool.assert_not_called()


def bind_result_target(agent, connection):
    agent.policy.fixed_arguments["section"] = "Operations"
    agent.policy.proposal_page_parameter = "path"
    agent.policy.proposal_section_parameter = "section"
    connection.spec.inputSchema["properties"]["section"] = {"type": "string"}
    connection.spec.inputSchema["required"].append("section")


def test_result_adapter_selects_exact_content_evidence_and_preserves_origin(harness, result_command):
    async def run():
        agent, remote, connection = harness
        bind_result_target(agent, connection)
        result_command["result"]["evidence"].append(
            {**result_command["result"]["evidence"][0], "id": "unused", "excerpt": "Not referenced"}
        )
        session = agent.create_session()
        approval = await propose(agent, session, result_command)
        record = await inspect(agent, session, approval.id)
        assert record["run_id"] == result_command["result"]["request_id"]
        assert record["origin"]["proposal_index"] == 0
        assert record["origin"]["target_section"] == "Operations"
        assert len(record["origin"]["result_sha256"]) == 64
        assert [item["id"] for item in record["evidence"]] == ["test"]
        assert record["arguments"]["content"] == result_command["result"]["proposed_changes"][0]["proposed_content"]
        Draft202012Validator(PendingCall.model_json_schema()).validate(record)
        Draft202012Validator(COMMAND.json_schema()).validate(result_command)
        remote.call_tool.assert_not_called()
        changed = await agent.run(
            json.dumps({"action": "modify", "pending_id": approval.id, "feedback": "Reword", "content": "New"}),
            session=session,
        )
        new = next(c for c in changed.messages[0].contents if c.type == "function_approval_request")
        modified_record = await inspect(agent, session, new.id)
        assert modified_record["origin"] == record["origin"]
        assert modified_record["args_hash"] != record["args_hash"]
        await agent.run(decision(new), session=session)
        remote.call_tool.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad", ["page", "section", "index", "boolean_index", "evidence", "review_flag", "content", "unbound", "agent"]
)
def test_result_adapter_fails_closed(harness, result_command, bad):
    async def run():
        agent, remote, connection = harness
        if bad != "unbound":
            bind_result_target(agent, connection)
        change = result_command["result"]["proposed_changes"][0]
        if bad == "page":
            change["target_page"] = "/real-page"
        elif bad == "section":
            change["target_section"] = "Security"
        elif bad == "index":
            result_command["proposal_index"] = 1
        elif bad == "boolean_index":
            result_command["proposal_index"] = True
        elif bad == "evidence":
            change["evidence_refs"] = ["unknown"]
        elif bad == "review_flag":
            result_command["result"]["requires_human_review"] = False
        elif bad == "content":
            change["proposed_content"] = "x" * 16001
        elif bad == "agent":
            result_command["result"]["provenance"]["agent_name"] = "unrelated-agent"
        with pytest.raises(ValueError):
            await propose(agent, agent.create_session(), result_command)
        remote.call_tool.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("flag", ["--print-command-schema", "--print-state-schema"])
def test_schema_cli_does_not_require_policy_credentials_or_state(flag):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "documentation_agent.approval", flag],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    schema = json.loads(result.stdout)
    Draft202012Validator.check_schema(schema)
    assert schema == (COMMAND.json_schema() if flag == "--print-command-schema" else PendingCall.model_json_schema())


def test_result_to_native_approval_through_real_local_mcp_transport(policy, result_command, monkeypatch):
    """Real HTTP/MCP and official Toolbox SDK; only identity/remote endpoint are substituted."""
    import socket

    import uvicorn
    from agent_framework_foundry_hosting import FoundryToolbox as OfficialToolbox
    from azure.core.credentials import AccessToken
    from mcp.server.fastmcp import FastMCP

    calls = []
    headers = []
    credentials = []
    policy.fixed_arguments["section"] = "Operations"
    policy.proposal_page_parameter = "path"
    policy.proposal_section_parameter = "section"
    mcp = FastMCP("approval-integration", stateless_http=True, json_response=True)

    @mcp.tool(name=policy.tool_name)
    def replace_test_section(project: str, wiki: str, path: str, section: str, content: str) -> dict:
        call = {"project": project, "wiki": wiki, "path": path, "section": section, "content": content}
        calls.append(call)
        return {"updated": call}

    app = mcp.streamable_http_app()

    class ObserveHeaders:
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                headers.append(dict(scope["headers"]))
            await app(scope, receive, send)

    class Credential:
        def __init__(self):
            self.closed = False
            credentials.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def get_token(self, *scopes, **kwargs):
            assert scopes == ("https://ai.azure.com/.default",)
            return AccessToken("local-test-token-not-a-credential", 4102444800)

    async def run():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            endpoint = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
            server = uvicorn.Server(uvicorn.Config(ObserveHeaders(), log_level="error", lifespan="on"))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if task.done():
                            await task
                            pytest.fail("Local MCP server exited before readiness.")
                        await asyncio.sleep(0.02)

                def toolbox(credential, **kwargs):
                    assert kwargs.pop("url") == policy.toolbox_endpoint
                    return OfficialToolbox(credential, url=endpoint, **kwargs)

                monkeypatch.setattr("documentation_agent.approval.FoundryToolbox", toolbox)
                monkeypatch.setattr("documentation_agent.approval.ManagedIdentityCredential", Credential)

                def client():
                    hosted = ResponsesHostServer(ToolApprovalAgent(policy, allow_local=True), history_source="agent")
                    return AsyncClient(transport=ASGITransport(app=hosted), base_url="http://localhost")

                async def post(http, body):
                    response = await http.post("/responses", json={**body, "stream": False})
                    response.raise_for_status()
                    return response.json()

                async def submit(http):
                    first = await post(http, {"input": json.dumps(result_command)})
                    assert first["status"] == "completed", first
                    approval = next(item for item in first["output"] if item["type"] == "mcp_approval_request")
                    text = next(
                        p["text"] for i in first["output"] if i["type"] == "message" for p in i["content"]
                    )
                    return first, approval, text.splitlines()[0].removeprefix("Pending ID: ")

                def decide_body(first, approval, approve=True):
                    return {
                        "previous_response_id": first["id"],
                        "input": [
                            {"type": "mcp_approval_response", "approval_request_id": approval["id"], "approve": approve}
                        ],
                    }

                async with client() as http:
                    first, approval, _ = await submit(http)
                    assert not calls
                # Recreate the hosting application; native previous-response state and
                # our pending state are both loaded from the same SDK local directory.
                async with client() as http:
                    approved = await post(http, decide_body(first, approval))
                    assert approved["status"] == "completed", approved
                    content = result_command["result"]["proposed_changes"][0]["proposed_content"]
                    assert calls == [policy.arguments(content)]
                    replay = await post(http, decide_body(first, approval))
                    assert replay["status"] == "failed", replay
                    rejected_first, rejected_approval, _ = await submit(http)
                    rejected = await post(http, decide_body(rejected_first, rejected_approval, False))
                    assert rejected["status"] == "completed", rejected
                    assert len(calls) == 1
                    old, old_approval, pending_id = await submit(http)
                    modified = await post(
                        http,
                        {
                            "previous_response_id": old["id"],
                            "input": json.dumps(
                                {
                                    "action": "modify",
                                    "pending_id": pending_id,
                                    "feedback": "Revise",
                                    "content": "Revised",
                                }
                            ),
                        },
                    )
                    assert modified["status"] == "completed", modified
                    new = next(item for item in modified["output"] if item["type"] == "mcp_approval_request")
                    assert (await post(http, decide_body(old, old_approval)))["status"] == "failed"
                    assert len(calls) == 1
                    assert (await post(http, decide_body(modified, new)))["status"] == "completed"
                    assert calls[-1] == policy.arguments("Revised")
                    concurrent, concurrent_approval, _ = await submit(http)
                    outcomes = await asyncio.gather(
                        post(http, decide_body(concurrent, concurrent_approval)),
                        post(http, decide_body(concurrent, concurrent_approval)),
                    )
                    assert sorted(item["status"] for item in outcomes) == ["completed", "failed"]
                    assert len(calls) == 3
                assert headers
                assert all(h.get(b"authorization") == b"Bearer local-test-token-not-a-credential" for h in headers)
                assert credentials and all(c.closed for c in credentials)
            finally:
                server.should_exit = True
                try:
                    await asyncio.wait_for(task, timeout=10)
                except TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise

    asyncio.run(run())


SANDBOX_POLICY = Path(__file__).resolve().parents[2] / "src/agents/documentation-agent/approval/sandbox-policy.json"

# Live schema of the remote ADO MCP wiki write tool (AzureDevOps.Mcp 1.0.0.0, tools/list, X-MCP-Toolsets: wiki).
WIKI_UPSERT_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "wikiIdentifier": {"type": "string"},
        "path": {"type": "string"},
        "content": {"type": "string"},
        "project": {"type": "string"},
        "etag": {"type": ["string", "null"], "default": None},
        "branch": {"type": "string", "default": "wikiMaster"},
    },
    "required": ["wikiIdentifier", "path", "content", "project"],
}


def test_packaged_sandbox_policy_targets_only_the_disposable_page(monkeypatch):
    monkeypatch.setenv("DOCUMENTATION_APPROVAL_POLICY", str(SANDBOX_POLICY))
    loaded = ToolApprovalPolicy.from_environment()

    assert loaded.tool_name == "ado___wiki_upsert_page"
    assert "/toolboxes/documentation-agent-write/versions/1/mcp" in loaded.toolbox_endpoint
    assert loaded.fixed_arguments["path"] == "/Workshop/Approval-Sandbox"
    assert loaded.auth_mode == "managed_identity"
    assert "etag" not in loaded.fixed_arguments
    Draft202012Validator(WIKI_UPSERT_PAGE_SCHEMA).validate(loaded.arguments("Sandbox text."))
