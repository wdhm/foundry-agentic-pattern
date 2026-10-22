import asyncio
import hashlib
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

from contracts.drafts import DraftPublished, content_hash
from contracts.v1 import AgentResult, Evidence
from contracts.wiki import WikiDraftBundle, WikiSnapshot

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


@pytest.mark.parametrize("merged", [False, True])
def test_real_http_pipeline_to_proactive_card_and_user_open(harness, tmp_path, monkeypatch, merged):
    async def run():
        flow, teams, assessor, _, connection, _ = harness
        flow.policy.merged_pr_drafts = merged
        draft_reader = AsyncMock()
        monkeypatch.setattr("documentation_agent.draft_reader.ToolboxDraftReader", lambda settings: draft_reader)
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
                "/invocations", headers=pipeline_headers,
                json=push().model_copy(update={"pull_request_id": 12 if merged else None}).model_dump(mode="json"),
            )
            assert notification.status_code == 200, notification.text
            if merged:
                assert notification.json()["state"] == "draft_ready"
                assert not continued
                draft_reader.return_value = notification.json()["content"]
                notification = await client.post("/invocations", headers=pipeline_headers, json={
                    "interface_version": "1.0.0", "action": "draft_published",
                    "event_id": notification.json()["event_id"], "draft_commit": "b" * 40,
                })
                assert notification.status_code == 200, notification.text
            assert continued[0].conversation.id == "personal-chat"
            notice = sent[-1].attachments[0].content
            open_review = await client.post(
                "/activity/messages", headers=reviewer_headers, json=activity(
                    value=button(notice, "Review decision" if merged else "Open review")
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
            assert ("rejected" if merged else "Proposal rejected") in json.dumps(sent[-1].attachments[0].content)
            connection.invoke_once.assert_not_called()

    asyncio.run(run())


def merged_flow(harness):
    flow, teams, _, _, _, _ = harness
    flow.policy.merged_pr_drafts = True
    flow.read_draft = AsyncMock()
    teams.push_flow = flow
    return push().model_copy(update={"pull_request_id": 12})


def test_draft_must_be_verified_before_notification_or_approval(harness, monkeypatch):
    async def run():
        flow, teams, assessor, notify, connection, stores = harness
        request = merged_flow(harness)
        prepared = await register_and_send(harness, monkeypatch, request)
        assert prepared["state"] == "draft_ready"
        assert prepared["content_sha256"] == content_hash(prepared["content"])
        assert assessor.assess.call_args.args[0].subject.pr_reference == REPO + "/pullrequest/12"
        notify.assert_not_called()
        connection.invoke_once.assert_not_called()
        with platform():
            with pytest.raises(ValueError, match="not ready"):
                await flow.open_review(activity(), UUID(prepared["event_id"]))
        flow.read_draft.return_value = prepared["content"]
        published = DraftPublished(
            interface_version="1.0.0", action="draft_published", event_id=prepared["event_id"], draft_commit="b" * 40,
        )
        with platform(CALLER):
            done = await flow.publish_draft(published)
            duplicate = await flow.publish_draft(published)
        assert done["state"] == "notified" and duplicate["duplicate"]
        notify.assert_awaited_once()
        notification = notify.call_args.args[1]
        assert prepared["content"] not in json.dumps(notification)
        assert "version=GC" + "b" * 40 in json.dumps(notification)
        with platform():
            review = await flow.open_review(activity(), UUID(prepared["event_id"]))
            assert len(json.dumps(review)) < 4000
            assert prepared["content"] not in json.dumps(review)
            approve = button(review, "Approve")
            item = await stores[STORE_NAME].get_item(approve["pending_id"])
            assert item.value["arguments"]["content"] == prepared["content"]
            await teams.handle(activity(value=approve))
            connection.invoke_once.assert_awaited_once()
            assert connection.invoke_once.call_args.args[0]["content"] == prepared["content"]

    asyncio.run(run())


def test_draft_mismatch_and_untrusted_finalize_do_not_notify(harness, monkeypatch):
    async def run():
        flow, _, _, notify, connection, _ = harness
        prepared = await register_and_send(harness, monkeypatch, merged_flow(harness))
        flow.read_draft.return_value = prepared["content"] + "\nchanged"
        published = DraftPublished(
            interface_version="1.0.0", action="draft_published", event_id=prepared["event_id"], draft_commit="b" * 40,
        )
        with platform(), pytest.raises(PermissionError):
            await flow.publish_draft(published)
        with platform(CALLER), pytest.raises(ValueError, match="bytes differ"):
            await flow.publish_draft(published)
        notify.assert_not_called()
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_modified_proposal_does_not_reuse_original_draft_link(harness, monkeypatch):
    async def run():
        flow, teams, _, _, connection, _ = harness
        prepared = await register_and_send(harness, monkeypatch, merged_flow(harness))
        flow.read_draft.return_value = prepared["content"]
        with platform(CALLER):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
        with platform():
            original = await flow.open_review(activity(), UUID(prepared["event_id"]))
            edit = await teams.handle(activity(value=button(original, "Modify")))
            revised = await teams.handle(activity(value={
                **button(edit, "New proposal"), "content": "Explicitly revised text.", "feedback": "Reword",
            }))
            assert "View draft" not in json.dumps(revised)
            assert "Explicitly revised text." not in json.dumps(revised)
            assert [a["title"] for a in revised["actions"]] == ["Review revision", "Reject"]
            details = await teams.handle(activity(value=button(revised, "Review revision")))
            assert "Explicitly revised text." in json.dumps(details)
            with pytest.raises(ValueError, match="no longer pending"):
                await teams.handle(activity(value=button(original, "Approve")))
            await teams.handle(activity(value=button(details, "Reject")))
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_merged_policy_rejects_legacy_direct_push_and_recovers_ready_draft(harness, monkeypatch):
    async def run():
        flow, _, assessor, notify, _, _ = harness
        request = merged_flow(harness)
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        with platform(CALLER), pytest.raises(ValueError, match="completed pull request"):
            await flow.process(push())
        first = await register_and_send(harness, monkeypatch, request)
        with platform(CALLER):
            second = await flow.process(request)
            assert second["duplicate"]
            assert first["content"] == second["content"]
            with pytest.raises(ValueError, match="different pull request"):
                await flow.process(request.model_copy(update={"pull_request_id": 13}))
        assessor.assess.assert_awaited_once()
        notify.assert_not_called()

    asyncio.run(run())


def test_no_replacement_of_link_after_publication(harness, monkeypatch):
    async def run():
        flow = harness[0]
        prepared = await register_and_send(harness, monkeypatch, merged_flow(harness))
        flow.read_draft.return_value = prepared["content"]
        with platform(CALLER):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
            with pytest.raises(ValueError, match="replace the draft"):
                await flow.publish_draft(DraftPublished(
                    interface_version="1.0.0", action="draft_published",
                    event_id=prepared["event_id"], draft_commit="c" * 40,
                ))

    asyncio.run(run())


def test_superseded_draft_is_not_notified_after_slow_read(harness, monkeypatch):
    async def run():
        flow, _, _, notify, _, stores = harness
        prepared = await register_and_send(harness, monkeypatch, merged_flow(harness))

        async def slow_read(*args):
            latest = await stores[STORE].get_item("latest")
            await stores[STORE].set_item(
                "latest", {"event_id": str(uuid4()), "build_id": 101}, if_match=latest.etag,
            )
            return prepared["content"]

        flow.read_draft.side_effect = slow_read
        with platform(CALLER), pytest.raises(ValueError, match="superseded during"):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
        notify.assert_not_called()

    asyncio.run(run())


def test_changed_policy_and_failed_verification_leave_no_approval(harness, monkeypatch):
    async def run():
        flow, _, _, notify, connection, _ = harness
        prepared = await register_and_send(harness, monkeypatch, merged_flow(harness))
        flow.policy.wiki_page = "/changed"
        with platform(CALLER), pytest.raises(ValueError, match="policy changed"):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
        notify.assert_not_called()
        flow.read_draft.assert_not_called()
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_uncertain_draft_delivery_cannot_be_reposted_but_can_be_opened(harness, monkeypatch):
    async def run():
        flow, _, _, notify, connection, _ = harness
        prepared = await register_and_send(harness, monkeypatch, merged_flow(harness))
        flow.read_draft.return_value = prepared["content"]
        notify.side_effect = TimeoutError("Delivery uncertain")
        published = DraftPublished(
            interface_version="1.0.0", action="draft_published",
            event_id=prepared["event_id"], draft_commit="b" * 40,
        )
        with platform(CALLER):
            with pytest.raises(TimeoutError):
                await flow.publish_draft(published)
            with pytest.raises(ValueError, match="uncertain delivery"):
                await flow.publish_draft(published)
        with platform():
            review = await flow.open_review(activity(), UUID(prepared["event_id"]))
            assert "View draft" in json.dumps(review)
        notify.assert_awaited_once()
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_draft_without_proposed_changes_has_no_write_buttons(harness, monkeypatch):
    async def run():
        flow, _, assessor, _, connection, _ = harness
        request = merged_flow(harness)

        def no_change(request):
            result = result_for(request)
            result.proposed_changes = []
            return result

        assessor.assess.side_effect = no_change
        prepared = await register_and_send(harness, monkeypatch, request)
        flow.read_draft.return_value = prepared["content"]
        with platform(CALLER):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
        with platform():
            review = await flow.open_review(activity(), UUID(prepared["event_id"]))
            assert [a["title"] for a in review["actions"]] == ["View findings"]
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def page_snapshot(content, path="/Order Sync/Overview"):
    raw = content.encode()
    etag = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return WikiSnapshot(path=path, content=content, etag=etag, uri="https://dev.azure.com/test/wiki")


def page_flow(harness):
    flow, teams, assessor, _, connection, _ = harness
    current = [page_snapshot("# Order Sync overview\n\nKeep this introduction.\n\n## Owner\n\nExisting owner info.\n")]
    flow.policy.compose_wiki_page = True
    flow.policy.merged_pr_drafts = True
    flow.read_draft = AsyncMock()
    flow.read_notes = AsyncMock()
    flow.read_wiki = AsyncMock(side_effect=lambda path: current[0])
    policy = ToolApprovalPolicy(
        toolbox_endpoint=teams.agent.policy.toolbox_endpoint, tool_name="ado___wiki_upsert_page",
        content_parameter="content", wiki_etag_parameter="etag",
        fixed_arguments={"project": "project", "wikiIdentifier": "wiki", "path": "/Order Sync/Overview",
                         "branch": "wikiMaster"},
    )
    connection.spec.name = policy.tool_name
    connection.spec.inputSchema["properties"].update({
        key: {"type": "string"} for key in ("project", "wikiIdentifier", "branch", "etag")
    })
    teams.agent = ToolApprovalAgent(policy, connector=teams.agent.connector, wiki_reader=flow.read_wiki)

    async def write(args):
        assert args["etag"] == current[0].etag
        current[0] = page_snapshot(args["content"])
        return {"updated": True}

    connection.invoke_once.side_effect = write

    def analyze(request):
        result = result_for(request)
        result.evidence.append(Evidence.model_validate({
            "id": "wiki", "source": "wiki", "uri": current[0].uri,
            "version": current[0].etag, "excerpt": "Keep this introduction.",
        }))
        return result

    assessor.assess.side_effect = analyze
    return current


def test_real_page_flow_preserves_page_and_publishes_only_reviewed_final_content(harness, monkeypatch):
    async def run():
        flow, teams, _, notify, connection, _ = harness
        current = page_flow(harness)
        before = current[0]
        request = push().model_copy(update={"pull_request_id": 12})
        prepared = await register_and_send(harness, monkeypatch, request)
        assert prepared["content"].startswith(before.content)
        assert "## Retry\n\nRetries three times." in prepared["content"]
        assert "## Findings" not in prepared["content"]
        assert "## Findings" in prepared["review_notes"]
        assert before.etag in prepared["review_notes"]
        assert current[0] == before
        flow.read_draft.return_value = prepared["content"]
        flow.read_notes.return_value = prepared["review_notes"]
        with platform(CALLER):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
        assert "Changes & evidence" in json.dumps(notify.call_args.args[1])
        connection.invoke_once.assert_not_called()
        with platform():
            card = await flow.open_review(activity(), UUID(prepared["event_id"]))
            assert "sandbox" not in json.dumps(card).lower()
            assert "/Order Sync/Overview" in json.dumps(card)
            await teams.handle(activity(value=button(card, "Approve")))
        assert current[0].content == prepared["content"]
        assert current[0].etag != before.etag
        connection.invoke_once.assert_awaited_once()
        assert connection.invoke_once.call_args.args[0]["etag"] == before.etag

    asyncio.run(run())


def test_real_page_changed_during_assessment_does_not_produce_draft(harness, monkeypatch):
    async def run():
        flow, _, _, notify, connection, _ = harness
        current = page_flow(harness)
        flow.read_wiki.side_effect = [current[0], page_snapshot("Someone edited the wiki")]
        with pytest.raises(ValueError, match="changed during assessment"):
            await register_and_send(harness, monkeypatch, push().model_copy(update={"pull_request_id": 12}))
        notify.assert_not_called()
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_real_page_review_notes_are_verified_not_trusted_from_publisher(harness, monkeypatch):
    async def run():
        flow, _, _, notify, _, _ = harness
        page_flow(harness)
        prepared = await register_and_send(harness, monkeypatch, push().model_copy(update={"pull_request_id": 12}))
        flow.read_draft.return_value = prepared["content"]
        flow.read_notes.return_value = "Fabricated reassuring diff"
        with platform(CALLER), pytest.raises(ValueError, match="review notes differ"):
            await flow.publish_draft(DraftPublished(
                interface_version="1.0.0", action="draft_published",
                event_id=prepared["event_id"], draft_commit="b" * 40,
            ))
        notify.assert_not_called()

    asyncio.run(run())


def wiki_mode(harness):
    flow, teams, _, _, _, _ = harness
    current = page_flow(harness)
    pages = {}
    flow.policy.draft_storage = "wiki"
    teams.agent.policy.review_draft_prefix = "/Drafts/Order Sync"

    async def read(path):
        return current[0] if path == "/Order Sync/Overview" else pages[path]

    async def publish(event, pr_id, content, notes, *, revision_id=None):
        tail = f"-revision-{revision_id}" if revision_id else ""
        path = f"/Drafts/Order Sync/PR-{pr_id}-{event}{tail}"
        pages[path] = page_snapshot(content, path)
        review = None
        if notes is not None:
            pages[path + "-review"] = page_snapshot(notes, path + "-review")
            review = pages[path + "-review"]
        return WikiDraftBundle(page=pages[path], notes=review)

    flow.read_wiki = AsyncMock(side_effect=read)
    teams.agent.wiki_reader = flow.read_wiki
    flow.wiki_publisher = type("Publisher", (), {})()
    flow.wiki_publisher.publish = AsyncMock(side_effect=publish)
    return current, pages


def test_automatic_wiki_draft_then_human_approval_copies_exact_page(harness, monkeypatch):
    async def run():
        flow, teams, _, notify, connection, stores = harness
        current, pages = wiki_mode(harness)
        before = current[0]
        event = await register_and_send(harness, monkeypatch, push().model_copy(update={"pull_request_id": 12}))
        assert event["state"] == "notified"
        assert len(pages) == 2
        assert current[0] == before
        connection.invoke_once.assert_not_called()
        notice = notify.call_args.args[1]
        assert [a["title"] for a in notice["actions"]] == ["Draft page", "Changes", "Review"]
        with platform():
            review = await flow.open_review(activity(), UUID(event["event_id"]))
            approval = button(review, "Approve")
            stored = await stores[STORE_NAME].get_item(approval["pending_id"])
            assert stored.value["review_draft"]["path"].startswith("/Drafts/Order Sync/PR-12-")
            assert stored.value["review_notes"]["path"].endswith("-review")
            expected = stored.value["arguments"]["content"]
            await teams.handle(activity(value=approval))
            assert current[0].content == expected
            assert len(pages) == 2  # Draft pages are retained after approval.
        connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("changed", ["draft", "notes", "destination"])
def test_changed_wiki_draft_notes_or_destination_prevents_approval(harness, monkeypatch, changed):
    async def run():
        flow, teams, _, _, connection, _ = harness
        current, pages = wiki_mode(harness)
        event = await register_and_send(harness, monkeypatch, push().model_copy(update={"pull_request_id": 12}))
        with platform():
            review = await flow.open_review(activity(), UUID(event["event_id"]))
            if changed == "destination":
                current[0] = page_snapshot("Concurrent change to published wiki")
            else:
                path = next(p for p in pages if p.endswith("-review") == (changed == "notes"))
                pages[path] = page_snapshot("Edited after review card", path)
            with pytest.raises(ValueError, match="changed"):
                await teams.handle(activity(value=button(review, "Approve")))
            connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_wiki_modify_publishes_new_review_draft_and_requires_fresh_decision(harness, monkeypatch):
    async def run():
        flow, teams, _, _, connection, _ = harness
        current, pages = wiki_mode(harness)
        original_page = current[0]
        event = await register_and_send(harness, monkeypatch, push().model_copy(update={"pull_request_id": 12}))
        with platform():
            review = await flow.open_review(activity(), UUID(event["event_id"]))
            edit = await teams.handle(activity(value=button(review, "Modify")))
            replacement = await teams.handle(activity(value={
                **button(edit, "New proposal"),
                "content": "# Complete revised page\n\nReviewer content.", "feedback": "Clarify wording",
            }))
            assert len(pages) == 4
            assert current[0] == original_page
            assert "Draft page" in json.dumps(replacement)
            with pytest.raises(ValueError, match="no longer pending"):
                await teams.handle(activity(value=button(review, "Approve")))
            await teams.handle(activity(value=button(replacement, "Approve")))
            assert current[0].content == "# Complete revised page\n\nReviewer content."
            assert len(pages) == 4
            connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_uncertain_wiki_draft_publication_is_not_repeated(harness, monkeypatch):
    async def run():
        flow, _, _, notify, connection, stores = harness
        wiki_mode(harness)
        flow.wiki_publisher.publish.side_effect = TimeoutError("Unknown draft creation outcome")
        request = push().model_copy(update={"pull_request_id": 12})
        with pytest.raises(TimeoutError):
            await register_and_send(harness, monkeypatch, request)
        key = event_key(flow.policy, request.commit_sha)
        assert (await stores[STORE].get_item(key)).value["state"] == "draft_publication_unknown"
        with platform(CALLER), pytest.raises(ValueError, match="incomplete"):
            await flow.process(request)
        flow.wiki_publisher.publish.assert_awaited_once()
        connection.invoke_once.assert_not_called()
        notify.assert_not_called()

    asyncio.run(run())
