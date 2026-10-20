import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agent_framework import AgentSession
from azure.ai.agentserver.core import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)
from azure.ai.agentserver.core.storage import FoundryStateStore
from documentation_agent.approval import STORE_NAME, InspectCall, PendingCall, ToolApprovalAgent, ToolApprovalPolicy
from documentation_agent.main import create_server
from documentation_agent.teams import BINDING_STORE, CardAction, TeamsApproval, create_teams_server
from documentation_agent.teams_card import MAX_CARD_BYTES
from httpx import ASGITransport, AsyncClient
from mcp.types import Tool
from microsoft_agents.activity import Activity, ResourceResponse

TENANT = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-000000000002"
SESSION = "00000000-0000-4000-8000-000000000003"


def activity(text=None, value=None):
    return Activity.model_validate({
        "type": "message",
        "id": str(uuid4()),
        "channelId": "msteams",
        "from": {"id": "teams-user", "aadObjectId": USER},
        "recipient": {"id": "test-bot"},
        "conversation": {"id": "personal-conversation", "conversationType": "personal", "tenantId": TENANT},
        "channelData": {"tenant": {"id": TENANT}},
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
        "text": text,
        "value": value,
    })


@contextmanager
def platform(user=USER, session=SESSION, call_id="opaque-platform-call"):
    token = set_request_context(FoundryAgentRequestContext(user_id=user, session_id=session, call_id=call_id))
    try:
        yield
    finally:
        reset_request_context(token)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT", raising=False)
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("DOCUMENTATION_TEAMS_TENANT_ID", TENANT)
    monkeypatch.setenv("DOCUMENTATION_ENABLE_TEAMS", "true")
    stores = {}
    for name in (STORE_NAME, BINDING_STORE, "function_approvals", "agent_sessions"):
        stores[name] = asyncio.run(FoundryStateStore.get_or_create(name, user_isolation=True))

    async def local_store(name, **kwargs):
        assert kwargs["user_isolation"] is True
        return stores[name]

    monkeypatch.setattr(FoundryStateStore, "get_or_create", local_store)
    policy = ToolApprovalPolicy(
        toolbox_endpoint="https://test.services.ai.azure.com/api/projects/test/toolboxes/test-write/versions/1/mcp"
        "?api-version=v1",
        tool_name="ado___test_write",
        fixed_arguments={"project": "test", "path": "/Workshop/Test"},
        content_parameter="content",
    )
    connection = type("Connection", (), {})()
    connection.spec = Tool(
        name=policy.tool_name,
        inputSchema={
            "type": "object",
            "properties": {key: {"type": "string"} for key in ("project", "path", "content")},
            "required": ["project", "path", "content"],
            "additionalProperties": False,
        },
    )
    connection.invoke_once = AsyncMock(return_value={"written": True})

    @asynccontextmanager
    async def connector(_):
        yield connection

    agent = ToolApprovalAgent(policy, connector=connector)
    handler = TeamsApproval(agent, UUID(TENANT))
    return agent, handler, connection, stores


@pytest.fixture
def proposal():
    return {
        "action": "propose",
        "run_id": str(uuid4()),
        "content": "Full replacement text.\n[Do not interpret as a link](https://example.com).",
        "evidence": [{
            "id": "test", "source": "git", "uri": "https://example.com/test",
            "version": "a" * 40, "excerpt": "Exact example evidence.",
        }],
    }


def submitted(card, title):
    return next(a["data"] for a in card["actions"] if a["title"] == title)


async def propose(handler, proposal):
    return await handler.handle(activity(text=json.dumps(proposal)))


def test_card_contains_exact_plain_content_evidence_and_safe_actions(harness, proposal, monkeypatch):
    async def run():
        _, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            result = await propose(handler, proposal)
        texts = [inline["text"] for element in result["body"] for inline in element.get("inlines", [])]
        assert proposal["content"] in texts
        assert proposal["evidence"][0]["uri"] in texts
        assert proposal["evidence"][0]["excerpt"] in texts
        assert "Version: " + "a" * 40 in texts
        assert all(a["type"] == "Action.Submit" and a["associatedInputs"] == "none" for a in result["actions"])
        for button in result["actions"]:
            assert set(button["data"]) == {"interface_version", "action", "pending_id", "args_hash"}
            CardAction.model_validate(button["data"])
        assert len(json.dumps(result).encode()) < MAX_CARD_BYTES
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("title,expected", [("Approve", "succeeded"), ("Reject", "rejected")])
def test_decisions_use_existing_runtime_and_replay_is_rejected(harness, proposal, monkeypatch, title, expected):
    async def run():
        agent, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            card = await propose(handler, proposal)
            value = submitted(card, title)
            result = await handler.handle(activity(value=value))
            assert [a["title"] for a in result["actions"]] == ["Refresh status"]
            response = await agent.execute(
                InspectCall(action="inspect", pending_id=value["pending_id"]).model_dump_json(),
                AgentSession(session_id=SESSION),
            )
            stored = PendingCall.model_validate_json(response[0].text)
            assert stored.status == expected
            assert stored.decided_by == USER
            with pytest.raises(ValueError, match="no longer pending"):
                await handler.handle(activity(value=value))
        assert connection.invoke_once.await_count == (1 if title == "Approve" else 0)
        if title == "Approve":
            assert connection.invoke_once.call_args.args[0] == agent.policy.arguments(proposal["content"])

    asyncio.run(run())


def test_modify_is_separate_form_new_approval_and_old_call_cannot_run(harness, proposal, monkeypatch):
    async def run():
        _, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            original = await propose(handler, proposal)
            edit = await handler.handle(activity(value=submitted(original, "Modify")))
            fields = {e["id"]: e for e in edit["body"] if e["type"] == "Input.Text"}
            assert fields["content"]["value"] == proposal["content"]
            assert fields["feedback"]["label"] and fields["feedback"]["isRequired"]
            assert "Approve" not in [a["title"] for a in edit["actions"]]
            connection.invoke_once.assert_not_called()
            replacement = await handler.handle(activity(value={
                **submitted(edit, "New proposal"), "content": "Revised full content.", "feedback": "Clarify it",
            }))
            assert submitted(replacement, "Approve")["pending_id"] != submitted(original, "Approve")["pending_id"]
            with pytest.raises(ValueError, match="no longer pending"):
                await handler.handle(activity(value=submitted(original, "Approve")))
            connection.invoke_once.assert_not_called()
            await handler.handle(activity(value=submitted(replacement, "Approve")))
            assert connection.invoke_once.call_args.args[0]["content"] == "Revised full content."

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        "user", "session", "conversation", "aad_user", "tenant", "channel", "group",
        "hash", "tool", "args", "missing_call",
    ],
)
def test_foreign_or_tampered_cards_never_dispatch(harness, proposal, monkeypatch, change):
    async def run():
        _, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            card = await propose(handler, proposal)
        value = deepcopy(submitted(card, "Approve"))
        message = activity(value=value)
        if change == "conversation":
            message.conversation.id = "different-conversation"
        elif change == "aad_user":
            message.from_property.aad_object_id = str(uuid4())
        elif change == "tenant":
            message.channel_data["tenant"]["id"] = str(uuid4())
        elif change == "channel":
            message.channel_id = "emulator"
        elif change == "group":
            message.conversation.conversation_type = "groupChat"
        elif change == "hash":
            value["args_hash"] = "f" * 64
        elif change == "tool":
            value["tool"] = "other"
        elif change == "args":
            value["content"] = "Tampered"
        with platform(
            user=str(uuid4()) if change == "user" else USER,
            session=str(uuid4()) if change == "session" else SESSION,
            call_id=None if change == "missing_call" else "opaque",
        ):
            with pytest.raises(ValueError):
                await handler.handle(message)
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_local_headers_do_not_enable_approval(harness):
    _, handler, connection, _ = harness
    with platform(), pytest.raises(ValueError, match="authenticated Foundry"):
        asyncio.run(handler.handle(activity(text="help")))
    connection.invoke_once.assert_not_called()


def test_reopen_after_handler_restart_and_competing_decisions(harness, proposal, monkeypatch):
    async def run():
        agent, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            original = await propose(handler, proposal)
            action = submitted(original, "Approve")
            restarted = TeamsApproval(agent, UUID(TENANT))
            reopened = await restarted.handle(activity(text="show " + action["pending_id"]))
            assert submitted(reopened, "Approve") == action
            outcomes = await asyncio.gather(
                restarted.handle(activity(value=action)), handler.handle(activity(value=action)), return_exceptions=True
            )
            assert sum(isinstance(value, ValueError) for value in outcomes) == 1
            connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_expired_cards_offer_no_decisions(harness, proposal, monkeypatch):
    async def run():
        _, handler, connection, stores = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            original = await propose(handler, proposal)
            action = submitted(original, "Approve")
            stored = await stores[STORE_NAME].get_item(action["pending_id"])
            value = {**stored.value, "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
            await stores[STORE_NAME].set_item(action["pending_id"], value, if_match=stored.etag)
            expired = await handler.handle(activity(text="show " + action["pending_id"]))
            assert [a["title"] for a in expired["actions"]] == ["Refresh status"]
            with pytest.raises(ValueError, match="expired"):
                await handler.handle(activity(value=action))
            connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_unknown_outcome_cannot_replay_and_card_does_not_claim_success(harness, proposal, monkeypatch):
    async def run():
        _, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            original = await propose(handler, proposal)
            action = submitted(original, "Approve")
            connection.invoke_once.side_effect = TimeoutError("external call timeout")
            with pytest.raises(TimeoutError):
                await handler.handle(activity(value=action))
            uncertain = await handler.handle(activity(text="show " + action["pending_id"]))
            assert uncertain["body"][0]["inlines"][0]["text"].startswith("Outcome unknown")
            assert [a["title"] for a in uncertain["actions"]] == ["Refresh status"]
            with pytest.raises(ValueError):
                await handler.handle(activity(value=action))
            connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_oversize_card_fails_without_silent_truncation(harness, proposal, monkeypatch):
    async def run():
        _, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        proposal["evidence"][0]["excerpt"] = "x" * 30000
        with platform(), pytest.raises(ValueError, match="size limit"):
            await propose(handler, proposal)
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_existing_responses_proposal_cannot_be_adopted_by_an_unbound_card(harness, proposal, monkeypatch):
    async def run():
        agent, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            output = await agent.execute(json.dumps(proposal), AgentSession(session_id=SESSION))
            pending_id = next(c.id for c in output if c.type == "function_approval_request")
            with pytest.raises(ValueError, match="predates Teams cards"):
                await handler.handle(activity(text="show " + pending_id))
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_binding_failure_cannot_deliver_an_actionable_card(harness, proposal, monkeypatch):
    async def run():
        _, handler, connection, stores = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        monkeypatch.setattr(stores[BINDING_STORE], "create_item", AsyncMock(side_effect=ConnectionError("store down")))
        with platform(), pytest.raises(ConnectionError):
            await propose(handler, proposal)
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("missing", ["content", "feedback"])
def test_modify_requires_valid_form_fields_without_voiding_old_proposal(harness, proposal, monkeypatch, missing):
    async def run():
        _, handler, connection, _ = harness
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform():
            original = await propose(handler, proposal)
            edit = await handler.handle(activity(value=submitted(original, "Modify")))
            value = {**submitted(edit, "New proposal"), "content": "New text", "feedback": "Reason"}
            value.pop(missing)
            with pytest.raises(ValueError, match="Invalid card action"):
                await handler.handle(activity(value=value))
            reopened = await handler.handle(activity(text="show " + value["pending_id"]))
            assert [a["title"] for a in reopened["actions"]] == ["Approve", "Modify", "Reject"]
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_activity_host_routes_card_and_decisions_and_preserves_responses(harness, proposal, monkeypatch):
    async def run():
        agent, _, connection, _ = harness
        host = create_teams_server(agent)
        sent = []

        async def send_activities(context, activities):
            sent.extend(activities)
            return [ResourceResponse(id=str(uuid4())) for _ in activities]

        monkeypatch.setattr(host.adapter, "send_activities", send_activities)
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        headers = {"x-agent-user-id": USER, "x-agent-foundry-call-id": "test-call", "x-agent-session-id": SESSION}
        async with AsyncClient(transport=ASGITransport(app=host), base_url="http://localhost") as client:
            first = await client.post(
                "/activity/messages", headers=headers, json=activity(text=json.dumps(proposal)).model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            )
            assert first.status_code < 300, first.text
            attachments = [a.attachments[0] for a in sent if a.attachments]
            assert len(attachments) == 1
            card = attachments[0].content
            assert attachments[0].content_type == "application/vnd.microsoft.card.adaptive"
            connection.invoke_once.assert_not_called()
            rejected = await client.post(
                "/activity/messages", headers=headers, json=activity(value=submitted(card, "Reject")).model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            )
            assert rejected.status_code < 300, rejected.text
            assert "Proposal rejected" in json.dumps(sent[-1].attachments[0].content)
            connection.invoke_once.assert_not_called()
            wire = await client.post(
                "/responses", headers=headers, json={"input": json.dumps(proposal), "stream": False},
            )
            assert wire.json()["status"] == "completed", wire.text
            assert any(item["type"] == "mcp_approval_request" for item in wire.json()["output"])
            # A fresh Teams proposal can be approved through the same registered
            # handler; the previously rejected card remains non-executable.
            new = await client.post(
                "/activity/messages", headers=headers, json=activity(text=json.dumps(proposal)).model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            )
            assert new.status_code < 300
            approve = submitted(sent[-1].attachments[0].content, "Approve")
            body = activity(value=approve).model_dump(mode="json", by_alias=True, exclude_none=True)
            completed = await client.post("/activity/messages", headers=headers, json=body)
            assert completed.status_code < 300, completed.text
            assert "Tool reported success" in json.dumps(sent[-1].attachments[0].content)
            connection.invoke_once.assert_awaited_once()
            duplicate = await client.post("/activity/messages", headers=headers, json=body)
            assert duplicate.status_code < 300
            assert "Request not completed" in sent[-1].text
            assert "no longer pending" in sent[-1].text
            connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_teams_requires_explicit_mode_and_tenant(harness, monkeypatch):
    agent, _, _, _ = harness
    monkeypatch.delenv("DOCUMENTATION_ENABLE_TEAMS")
    with pytest.raises(ValueError, match="explicit"):
        create_teams_server(agent)
    monkeypatch.setenv("DOCUMENTATION_ENABLE_TEAMS", "true")
    monkeypatch.setenv("DOCUMENTATION_MODE", "assessment")
    with pytest.raises(ValueError, match="approval mode"):
        create_server()
    monkeypatch.delenv("DOCUMENTATION_TEAMS_TENANT_ID")
    with pytest.raises(ValueError, match="TENANT_ID"):
        create_teams_server(agent)
