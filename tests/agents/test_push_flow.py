import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from azure.ai.agentserver.core import FoundryAgentRequestContext, reset_request_context, set_request_context
from azure.ai.agentserver.core.storage import FoundryStateStore
from documentation_agent.approval import STORE_NAME, ToolApprovalAgent, ToolApprovalPolicy
from documentation_agent.push_flow import STORE, PushFlow, PushPolicy, PushRequest, event_key
from documentation_agent.teams import BINDING_STORE, TeamsApproval, create_teams_server
from httpx import ASGITransport, AsyncClient
from mcp.types import Tool
from microsoft_agents.activity import Activity, ResourceResponse

from contracts.v1 import AgentResult

TENANT = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-000000000002"
CALLER = "00000000-0000-4000-8000-000000000003"
REPO = "https://dev.azure.com/test/project/_git/00000000-0000-4000-8000-000000000004"


@contextmanager
def platform(user=USER, session="teams-session"):
    token = set_request_context(FoundryAgentRequestContext(user_id=user, session_id=session, call_id="opaque"))
    try:
        yield
    finally:
        reset_request_context(token)


def activity(value=None, text=None):
    return Activity.model_validate({
        "type": "message", "id": str(uuid4()), "channelId": "msteams",
        "from": {"id": "user", "aadObjectId": USER},
        "recipient": {"id": "bot"},
        "conversation": {"id": "personal-chat", "conversationType": "personal", "tenantId": TENANT},
        "channelData": {"tenant": {"id": TENANT}}, "serviceUrl": "https://smba.trafficmanager.net/emea/",
        "value": value, "text": text,
    })


def result_for(request):
    return AgentResult.model_validate({
        "contract_version": "1.0.0", "request_id": str(request.request_id),
        "documentation_status": "gaps_found", "requires_human_review": True, "confidence": 0.8,
        "findings": [{
            "category": "retry", "severity": "medium",
            "description": "Document retry behavior", "evidence_refs": ["code"],
        }],
        "proposed_changes": [{
            "target_page": "/Order Sync/Overview", "target_section": "Retry",
            "proposed_content": "Retries three times.", "evidence_refs": ["code"],
        }],
        "missing_information": [],
        "evidence": [{
            "id": "code", "source": "git", "uri": "https://dev.azure.com/test/source",
            "version": request.subject.commit_sha, "excerpt": "maxAttempts=3",
        }],
        "provenance": {
            "agent_name": "documentation-agent", "agent_version": "0.4.0", "contract_version": "1.0.0",
            "model": "test", "model_version": "test", "prompt_version": "test", "policy_version": "test",
        },
    })


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT", raising=False)
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path / "state"))
    stores = {
        name: asyncio.run(FoundryStateStore.get_or_create(name, user_isolation=name != STORE))
        for name in [STORE, STORE_NAME, BINDING_STORE, "function_approvals", "agent_sessions"]
    }

    async def get_store(name, **kwargs):
        assert kwargs["user_isolation"] == (name != STORE)
        return stores[name]

    monkeypatch.setattr(FoundryStateStore, "get_or_create", get_store)
    policy = PushPolicy(
        repository_url=REPO, pipeline_id=10, caller_id=CALLER, reviewer_aad_id=USER,
        source_paths=["src/order_sync.py", "config/settings.json"], wiki_page="/Order Sync/Overview",
        documentation_standard_ref="https://example.com/standard",
    )
    write_policy = ToolApprovalPolicy(
        toolbox_endpoint="https://test.services.ai.azure.com/api/projects/test/toolboxes/write/versions/1/mcp?api-version=v1",
        tool_name="ado___write", fixed_arguments={"path": policy.sandbox_page}, content_parameter="content",
    )
    connection = type("Connection", (), {})()
    connection.spec = Tool(name="ado___write", inputSchema={
        "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    })
    connection.invoke_once = AsyncMock(return_value={"success": True})

    @asynccontextmanager
    async def connector(_):
        yield connection

    agent = ToolApprovalAgent(write_policy, connector=connector)
    teams = TeamsApproval(agent, UUID(TENANT))
    assessor = type("Assessor", (), {})()
    assessor.assess = AsyncMock(side_effect=result_for)
    notify = AsyncMock()
    flow = PushFlow(policy, teams, assessor, notify)
    teams.push_flow = flow
    return flow, teams, assessor, notify, connection, stores


def push(commit="a" * 40, build=100):
    return PushRequest(
        interface_version="1.0.0", repository_url=REPO, branch="refs/heads/main",
        pipeline_id=10, build_id=build, commit_sha=commit,
    )


async def register_and_send(harness, monkeypatch, request=None):
    flow, _, _, _, _, _ = harness
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
    with platform():
        await flow.register(activity(text="connect repo"))
    with platform(CALLER, "pipeline-session"):
        return await flow.process(request or push())


def button(card, title):
    return next(a["data"] for a in card["actions"] if a["title"] == title)


def test_push_notifies_without_write_and_reviewer_owns_new_approval(harness, monkeypatch):
    async def run():
        flow, teams, assessor, notify, connection, stores = harness
        received = await register_and_send(harness, monkeypatch)
        assert received["state"] == "notified"
        assert received["event_id"] == event_key(flow.policy, "a" * 40)
        args = assessor.assess.call_args.args[0]
        assert args.subject.commit_sha == "a" * 40
        assert args.task.scope == "information_review"
        assert args.subject.changed_paths == flow.policy.source_paths
        assert args.requested_by == "pipeline:10"
        notify.assert_awaited_once()
        connection.invoke_once.assert_not_called()
        with platform():
            review = await flow.open_review(activity(), UUID(received["event_id"]))
            approve = button(review, "Approve")
            stored = await stores[STORE_NAME].get_item(approve["pending_id"])
            assert stored.value["owner"] == USER
            assert stored.value["session_id"] == "teams-session"
            assert stored.value["arguments"]["path"] == "/Workshop/Approval-Sandbox"
            assert "Retries three times." in stored.value["arguments"]["content"]
            assert "not an automatic update" in stored.value["arguments"]["content"]
            await teams.handle(activity(value=approve))
            connection.invoke_once.assert_awaited_once()
            with pytest.raises(ValueError, match="no longer pending"):
                await teams.handle(activity(value=approve))

    asyncio.run(run())


def test_duplicate_and_foreign_pipeline_do_not_reassess(harness, monkeypatch):
    async def run():
        flow, _, assessor, notify, _, _ = harness
        await register_and_send(harness, monkeypatch)
        with platform(CALLER, "pipeline-session"):
            duplicate = await flow.process(push())
            assert duplicate["duplicate"] is True
            with pytest.raises(ValueError, match="pipeline"):
                await flow.process(push().model_copy(update={"pipeline_id": 11}))
        with platform(USER), pytest.raises(PermissionError):
            await flow.process(push("b" * 40, 101))
        assessor.assess.assert_awaited_once()
        notify.assert_awaited_once()

    asyncio.run(run())


def test_missing_registration_or_local_caller_rejected(harness, monkeypatch):
    async def run():
        flow = harness[0]
        with platform(CALLER), pytest.raises(PermissionError):
            await flow.process(push())
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform(CALLER), pytest.raises(ValueError, match="connect repo"):
            await flow.process(push())
        harness[2].assess.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["user", "conversation", "service_url", "tenant"])
def test_recipient_registration_is_not_payload_selectable(harness, monkeypatch, change):
    async def run():
        flow = harness[0]
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        message = activity()
        if change == "user":
            message.from_property.aad_object_id = str(uuid4())
        elif change == "conversation":
            message.conversation.conversation_type = "groupChat"
        elif change == "service_url":
            message.service_url = "https://attacker.example/capture"
        else:
            message.channel_data["tenant"]["id"] = str(uuid4())
        with platform(), pytest.raises(ValueError):
            await flow.register(message)

    asyncio.run(run())


def test_newer_event_invalidates_original_and_modified_cards(harness, monkeypatch):
    async def run():
        flow, teams, _, _, connection, _ = harness
        first = await register_and_send(harness, monkeypatch)
        with platform():
            review = await flow.open_review(activity(), UUID(first["event_id"]))
            edited = await teams.handle(activity(value=button(review, "Modify")))
            new = await teams.handle(activity(value={
                **button(edited, "New proposal"), "content": "Revised sandbox report", "feedback": "Review",
            }))
        with platform(CALLER):
            await flow.process(push("b" * 40, 101))
            with pytest.raises(ValueError, match="stale"):
                await flow.process(push("c" * 40, 99))
        with platform():
            with pytest.raises(ValueError, match="superseded"):
                await teams.handle(activity(value=button(new, "Approve")))
            await teams.handle(activity(value=button(new, "Reject")))
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_proactive_failure_is_not_success_or_automatically_reposted(harness, monkeypatch):
    async def run():
        flow, _, assessor, notify, connection, stores = harness
        notify.side_effect = TimeoutError("channel timeout")
        with pytest.raises(TimeoutError):
            await register_and_send(harness, monkeypatch)
        key = event_key(flow.policy, "a" * 40)
        assert (await stores[STORE].get_item(key)).value["state"] == "notification_unknown"
        with platform(CALLER), pytest.raises(ValueError, match="incomplete"):
            await flow.process(push())
        with platform():
            await flow.open_review(activity(), UUID(key))
        notify.assert_awaited_once()
        assessor.assess.assert_awaited_once()
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("wrong", ["request", "commit", "target"])
def test_invalid_assessment_never_notifies(harness, monkeypatch, wrong):
    async def run():
        flow, _, assessor, notify, _, stores = harness

        def bad(request):
            result = result_for(request)
            if wrong == "request":
                result.request_id = uuid4()
            elif wrong == "commit":
                result.evidence[0].version = "b" * 40
            else:
                result.proposed_changes[0].target_page = "/unreviewed"
            return result

        assessor.assess.side_effect = bad
        with pytest.raises(ValueError):
            await register_and_send(harness, monkeypatch)
        assert (await stores[STORE].get_item(event_key(flow.policy, "a" * 40))).value["state"] == "assessment_failed"
        notify.assert_not_called()

    asyncio.run(run())


def test_duplicate_open_reuses_pending_and_foreign_conversation_is_refused(harness, monkeypatch):
    async def run():
        flow, _, _, _, connection, _ = harness
        received = await register_and_send(harness, monkeypatch)
        event = UUID(received["event_id"])
        with platform():
            bad = activity()
            bad.conversation.id = "different-chat"
            with pytest.raises(ValueError, match="another reviewer"):
                await flow.open_review(bad, event)
            first = await flow.open_review(activity(), event)
            second = await flow.open_review(activity(), event)
            assert button(first, "Approve") == button(second, "Approve")
        with platform(session="different-session"), pytest.raises(ValueError):
            await flow.open_review(activity(), event)
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_real_http_pipeline_to_proactive_card_and_user_open(harness, tmp_path, monkeypatch):
    async def run():
        flow, teams, assessor, _, connection, _ = harness
        file = tmp_path / "push-policy.json"
        file.write_text(flow.policy.model_dump_json())
        env = {
            "DOCUMENTATION_ENABLE_TEAMS": "true", "DOCUMENTATION_TEAMS_TENANT_ID": TENANT,
            "DOCUMENTATION_ENABLE_PUSH_FLOW": "true", "DOCUMENTATION_PUSH_POLICY": str(file),
            "DOCUMENTATION_PUSH_READ_TOOLBOX": "https://test.services.ai.azure.com/api/projects/test/toolboxes/read/versions/1/mcp?api-version=v1",
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "TOOLBOX_ENDPOINT": teams.agent.policy.toolbox_endpoint, "AZURE_AI_MODEL_DEPLOYMENT_NAME": "test",
            "DOCUMENTATION_MODEL_VERSION": "test", "DOCUMENTATION_ADO_PROJECT": "project",
            "DOCUMENTATION_ADO_WIKI": "wiki", "DOCUMENTATION_ADO_ORGANIZATION": "test",
        }
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr("documentation_agent.assessment.AssessmentAgent", lambda settings: assessor)
        host = create_teams_server(teams.agent)
        sent = []
        continued = []

        async def send(context, activities):
            sent.extend(activities)
            return [ResourceResponse(id=str(uuid4())) for _ in activities]

        async def proactive(app_id, message, callback):
            from microsoft_agents.hosting.core import TurnContext

            continued.append(message)
            await callback(TurnContext(host.adapter, message))

        monkeypatch.setattr(host.adapter, "send_activities", send)
        monkeypatch.setattr(host.adapter, "continue_conversation", proactive)
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        monkeypatch.setenv("FOUNDRY_AGENT_INSTANCE_CLIENT_ID", "test-bot")
        reviewer_headers = {
            "x-agent-user-id": USER, "x-agent-foundry-call-id": "opaque", "x-agent-session-id": "teams-session",
        }
        pipeline_headers = {**reviewer_headers, "x-agent-user-id": CALLER, "x-agent-session-id": "pipeline-session"}
        async with AsyncClient(transport=ASGITransport(app=host), base_url="http://localhost") as client:
            posted = await client.post("/activity/messages", headers=reviewer_headers, json=activity(
                text="connect repo"
            ).model_dump(mode="json", by_alias=True, exclude_none=True))
            assert posted.status_code == 202, posted.text
            blocked = await client.post("/invocations", headers=reviewer_headers, json=push().model_dump(mode="json"))
            assert blocked.status_code == 403, blocked.text
            preflight = await client.post(
                "/invocations", headers=pipeline_headers, json={"interface_version": "1.0.0", "action": "preflight"},
            )
            assert preflight.json() == {"state": "caller_verified", "assessment_run": False}
            assessor.assess.assert_not_called()
            notification = await client.post(
                "/invocations", headers=pipeline_headers, json=push().model_dump(mode="json"),
            )
            assert notification.status_code == 200, notification.text
            assert continued[0].conversation.id == "personal-chat"
            notice = sent[-1].attachments[0].content
            open_review = await client.post(
                "/activity/messages", headers=reviewer_headers, json=activity(
                    value=button(notice, "Open review")
                ).model_dump(mode="json", by_alias=True, exclude_none=True),
            )
            assert open_review.status_code == 202, open_review.text
            pending = sent[-1].attachments[0].content
            assert [a["title"] for a in pending["actions"]] == ["Approve", "Modify", "Reject"]
            connection.invoke_once.assert_not_called()
            declined = await client.post(
                "/activity/messages", headers=reviewer_headers, json=activity(
                    value=button(pending, "Reject")
                ).model_dump(mode="json", by_alias=True, exclude_none=True),
            )
            assert declined.status_code == 202
            assert "Proposal rejected" in json.dumps(sent[-1].attachments[0].content)
            connection.invoke_once.assert_not_called()

    asyncio.run(run())
