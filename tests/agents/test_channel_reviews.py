import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from agent_framework import AgentSession, Message
from documentation_agent.approval import PendingCall
from documentation_agent.channel_policy import TeamsChannelPolicy
from documentation_agent.channel_reviews import STORE as CHANNEL_STORE
from documentation_agent.channel_reviews import ChannelReviews
from documentation_agent.conversation import ConversationService, ConversationSources
from documentation_agent.push_flow import STORE
from documentation_agent.settings import AssessmentSettings
from documentation_agent.teams import TeamsApproval, create_teams_server
from httpx import ASGITransport, AsyncClient
from microsoft_agents.activity import Activity, ResourceResponse
from test_push_flow import CALLER, REPO, TENANT, USER, activity, button, page_snapshot, platform, push, wiki_mode
from test_push_flow import harness as harness

SECOND = "00000000-0000-4000-8000-000000000005"
VIEWER = "00000000-0000-4000-8000-000000000006"
TEAM = "19:team@thread.tacv2"
CHANNEL = "19:channel@thread.tacv2"
THREAD = "review-root"


def channel_activity(text=None, value=None, *, user=USER, thread=THREAD):
    result = activity(text=text, value=value)
    result.from_property.aad_object_id = user
    result.conversation.conversation_type = "channel"
    result.conversation.id = CHANNEL + ";messageid=" + thread
    result.channel_data.update(team={"id": TEAM}, channel={"id": CHANNEL})
    result.reply_to_id = thread
    return result


def policy():
    return TeamsChannelPolicy(
        tenant_id=TENANT, team_id=TEAM, channel_id=CHANNEL, reviewer_aad_ids=[USER, SECOND],
    )


@pytest.fixture
def shared(harness, monkeypatch):
    flow, teams, assessor, notify, connection, stores = harness
    current, pages = wiki_mode(harness)
    teams.channels = ChannelReviews(teams, policy())
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
    scope = policy().scope(channel_activity())
    notify.return_value = scope
    return SimpleNamespace(
        flow=flow, teams=teams, assessor=assessor, notify=notify, connection=connection, stores=stores,
        current=current, pages=pages, scope=scope,
    )


async def deliver(shared, member_check=None):
    with platform():
        await shared.flow.register(
            channel_activity(text="enable notifications", thread="registration"), member_check=member_check,
        )
    with platform(CALLER, "pipeline"):
        event = await shared.flow.process(push().model_copy(update={"pull_request_id": 12}))
    return UUID(event["event_id"])


async def open_review(shared, event, user=USER, session="first-session"):
    with platform(user, session):
        return await shared.flow.open_review(channel_activity(user=user), event)


async def decide(shared, submitted, user=USER, session="first-session", member_check=None):
    with platform(user, session):
        return await shared.teams.handle(channel_activity(value=submitted, user=user), member_check=member_check)


@pytest.mark.parametrize("verb,expected,writes", [("Approve", "succeeded", 1), ("Reject", "rejected", 0)])
def test_two_reviewers_share_one_record_and_record_actual_actor(shared, verb, expected, writes):
    async def run():
        event = await deliver(shared)
        first = await open_review(shared, event)
        second = await open_review(shared, event, SECOND, "second-session")
        assert button(first, verb) == button(second, verb)
        result = await decide(shared, button(second, verb), SECOND, "second-session")
        pending = await shared.stores[CHANNEL_STORE].get_item(button(second, verb)["pending_id"])
        assert pending.value["owner"] == USER
        assert pending.value["decided_by"] == SECOND
        assert pending.value["decided_by_aad_id"] == SECOND
        assert pending.value["session_id"] == "first-session"
        assert pending.value["status"] == expected
        assert SECOND in json.dumps(result)
        assert shared.connection.invoke_once.await_count == writes
        # Another user/session sees the winning result instead of a second write.
        late = await decide(shared, button(first, verb), USER, "fresh-session")
        assert expected in json.dumps(late)
        assert shared.connection.invoke_once.await_count == writes
        if writes:
            assert shared.current[0].content == pending.value["arguments"]["content"]

    asyncio.run(run())


def test_viewer_can_read_and_discuss_but_cannot_decide_or_register(shared):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        readonly = await open_review(shared, event, VIEWER)
        assert not any(
            a.get("data", {}).get("action") in {"approve", "reject", "edit"} for a in readonly.get("actions", [])
        )
        assert "Read-only view" in json.dumps(readonly)
        for verb in ("Approve", "Reject", "Modify"):
            with pytest.raises(ValueError, match="not an authorized"):
                await decide(shared, button(card, verb), VIEWER)
        with platform(VIEWER), pytest.raises(ValueError, match="not an authorized"):
            await shared.flow.register(channel_activity(text="enable notifications", user=VIEWER))
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("alter", [
    "tenant", "team", "channel", "thread", "conversation", "personal", "group", "missing-call",
])
def test_wrong_scope_cannot_read_or_execute_shared_review(shared, alter):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        item = channel_activity(value=button(card, "Approve"), user=SECOND)
        if alter in {"tenant", "team", "channel"}:
            item.channel_data[alter]["id"] = "00000000-0000-4000-8000-000000000099" if alter == "tenant" else "foreign"
        elif alter == "thread":
            item.reply_to_id = "another-root"
            item.conversation.id = CHANNEL + ";messageid=another-root"
        elif alter == "conversation":
            item.conversation.id = "another-conversation;messageid=" + THREAD
        elif alter == "personal":
            item = activity(value=button(card, "Approve"))
        elif alter == "group":
            item.conversation.conversation_type = "groupChat"
        with platform(SECOND, "other", call_id=None if alter == "missing-call" else "call"), pytest.raises(ValueError):
            await shared.teams.handle(item)
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("verb", ["Approve", "Reject"])
def test_concurrent_decisions_dispatch_at_most_once(shared, verb):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        results = await asyncio.gather(
            decide(shared, button(card, "Approve"), USER),
            decide(shared, button(card, verb), SECOND, "other"),
        )
        assert all(isinstance(result, dict) for result in results)
        pending = (await shared.stores[CHANNEL_STORE].get_item(button(card, "Approve")["pending_id"])).value
        assert pending["status"] in {"succeeded", "rejected"}
        assert shared.connection.invoke_once.await_count == (1 if pending["status"] == "succeeded" else 0)
        assert pending["decided_by_aad_id"] in {USER, SECOND}

    asyncio.run(run())


def test_revoked_reviewer_cannot_use_existing_card(shared):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        shared.teams.channels = ChannelReviews(
            shared.teams, policy().model_copy(update={"reviewer_aad_ids": [UUID(USER)]}),
        )
        with pytest.raises(ValueError, match="not an authorized"):
            await decide(shared, button(card, "Approve"), SECOND)
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_shared_native_approval_cannot_be_used_through_responses(shared):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        record = PendingCall.model_validate(
            (await shared.stores[CHANNEL_STORE].get_item(button(card, "Approve")["pending_id"])).value,
        )
        native = record.approval().to_function_approval_response(True)
        with platform(USER, "first-session"), pytest.raises(ValueError, match="Unknown approval"):
            await shared.teams.agent.execute(Message("user", [native]), AgentSession(session_id="first-session"))
        with pytest.raises(ValueError, match="verified Teams channel handler"):
            await shared.teams.agent.decide(shared.stores[CHANNEL_STORE], native, USER, "first-session")
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("changed", ["draft", "notes", "destination"])
def test_shared_approval_retains_conditional_page_and_draft_checks(shared, changed):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        if changed == "destination":
            shared.current[0] = page_snapshot("Somebody changed the published page")
        else:
            path = next(p for p in shared.pages if p.endswith("-review") == (changed == "notes"))
            shared.pages[path] = page_snapshot("Changed draft bytes", path)
        with pytest.raises(ValueError, match="changed"):
            await decide(shared, button(card, "Approve"), SECOND)
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_shared_modify_voids_old_card_and_another_reviewer_can_approve_revision(shared):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        edit = await decide(shared, button(card, "Modify"), SECOND)
        replacement = await decide(shared, {
            **button(edit, "New proposal"), "content": "# Revised complete page", "feedback": "Clarify trigger",
        }, SECOND)
        assert len(shared.pages) == 4
        late = await decide(shared, button(card, "Approve"), USER)
        assert "modified" in json.dumps(late)
        shared.connection.invoke_once.assert_not_called()
        await decide(shared, button(replacement, "Approve"), USER, "new-session")
        shared.connection.invoke_once.assert_awaited_once()
        assert shared.current[0].content == "# Revised complete page"
        opened = await open_review(shared, event, VIEWER)
        assert "succeeded" in json.dumps(opened)

    asyncio.run(run())


def test_modify_claim_wins_before_revision_write_so_old_approval_cannot_execute(shared):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        edit = await decide(shared, button(card, "Modify"), SECOND)
        entered, proceed = asyncio.Event(), asyncio.Event()
        publish = shared.flow.wiki_publisher.publish.side_effect

        async def paused(*args, **kwargs):
            entered.set()
            await proceed.wait()
            return await publish(*args, **kwargs)

        shared.flow.wiki_publisher.publish.side_effect = paused
        modifying = asyncio.create_task(decide(shared, {
            **button(edit, "New proposal"), "content": "# Concurrent revision", "feedback": "Clarify",
        }, SECOND))
        await entered.wait()
        try:
            late = await decide(shared, button(card, "Approve"), USER)
            assert "modified" in json.dumps(late)
            shared.connection.invoke_once.assert_not_called()
        finally:
            proceed.set()
        replacement = await modifying
        await decide(shared, button(replacement, "Approve"), USER)
        assert shared.current[0].content == "# Concurrent revision"
        shared.connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["missing-mapping", "newer-event", "policy", "hash", "expiry"])
def test_shared_review_cannot_bypass_event_or_exact_call_guards(shared, fault):
    async def run():
        from datetime import UTC, datetime, timedelta

        event = await deliver(shared)
        card = await open_review(shared, event)
        submitted = button(card, "Approve")
        if fault == "missing-mapping":
            original_get = shared.stores[STORE].get_item

            async def missing(key):
                return None if key == "pending:" + submitted["pending_id"] else await original_get(key)

            shared.stores[STORE].get_item = missing
        elif fault == "newer-event":
            item = await shared.stores[STORE].get_item("latest")
            await shared.stores[STORE].set_item(
                "latest", {"event_id": "newer", "build_id": 200}, if_match=item.etag,
            )
        elif fault == "policy":
            shared.flow.policy.source_paths = ["different.py"]
        elif fault == "hash":
            submitted["args_hash"] = "f" * 64
        else:
            item = await shared.stores[CHANNEL_STORE].get_item(submitted["pending_id"])
            changed = {**item.value, "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
            await shared.stores[CHANNEL_STORE].set_item(submitted["pending_id"], changed, if_match=item.etag)
        with pytest.raises(ValueError):
            await decide(shared, submitted)
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_failed_revision_and_uncertain_write_never_retry(shared):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        edit = await decide(shared, button(card, "Modify"), SECOND)
        shared.flow.wiki_publisher.publish.side_effect = TimeoutError("Unknown draft write")
        with pytest.raises(TimeoutError):
            await decide(shared, {
                **button(edit, "New proposal"), "content": "# Revised", "feedback": "Clarify",
            }, SECOND)
        late = await decide(shared, button(card, "Approve"))
        assert "modified" in json.dumps(late)
        shared.connection.invoke_once.assert_not_called()
        assert shared.flow.wiki_publisher.publish.await_count == 2  # initial plus one revision

    asyncio.run(run())


def test_channel_write_timeout_reports_unknown_and_other_reviewer_cannot_retry(shared):
    async def run():
        event = await deliver(shared)
        card = await open_review(shared, event)
        shared.connection.invoke_once.side_effect = TimeoutError("Unknown external outcome")
        with pytest.raises(TimeoutError):
            await decide(shared, button(card, "Approve"))
        late = await decide(shared, button(card, "Approve"), SECOND)
        assert "outcome_unknown" in json.dumps(late)
        shared.connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def conversation():
    settings = AssessmentSettings(
        project_endpoint="https://test.services.ai.azure.com/api/projects/test",
        toolbox_endpoint="https://test.services.ai.azure.com/api/projects/test/toolboxes/read/versions/1/mcp?api-version=v1",
        model="test", model_version="test", ado_project="project", ado_wiki="wiki", ado_organization="test",
    )
    sources = ConversationSources.model_validate({
        "subject": {"repo": REPO, "commit_sha": "f" * 40},
        "context": {"wiki_page_paths": ["/Order Sync/Overview"], "work_item_ids": [1]},
        "documentation_standard_ref": "standard",
    })
    runner = SimpleNamespace(reply=AsyncMock(return_value="Read-only thread explanation."))
    return ConversationService(settings, sources, runner), runner


def test_thread_discussion_uses_event_commit_and_draft_without_private_history(shared):
    async def run():
        event = await deliver(shared)
        await open_review(shared, event)
        service, runner = conversation()
        shared.teams.conversation = service
        with platform():
            await shared.teams.handle(activity(text="Private personal context"))
            await shared.teams.handle(channel_activity(text="Explain this draft"))
        turns, _, guard = runner.reply.call_args.args
        assert [turn.text for turn in turns] == ["Explain this draft"]
        assert guard.request.subject.commit_sha == "a" * 40
        assert len(guard.request.context.wiki_page_paths) == 3
        with platform(SECOND, "second-session"):
            await shared.teams.handle(channel_activity(text="What are the gaps?", user=SECOND))
        assert len(runner.reply.call_args.args[0]) == 1
        with platform():
            await shared.teams.handle(channel_activity(text="Different thread", thread="other"))
        assert runner.reply.call_args.args[2].request.subject.commit_sha == "f" * 40
        assert len(runner.reply.call_args.args[2].request.context.wiki_page_paths) == 1

    asyncio.run(run())


def test_registered_channel_does_not_overwrite_personal_recipient(shared):
    async def run():
        await shared.stores[STORE].create_item("recipient", {"existing": "personal"})
        await deliver(shared)
        assert (await shared.stores[STORE].get_item("recipient")).value == {"existing": "personal"}
        with platform(), pytest.raises(ValueError, match="verified channel"):
            await shared.flow.register(activity(text="connect repo"))

    asyncio.run(run())


def test_channel_registration_and_shared_review_survive_handler_session_restart(shared):
    async def run():
        event = await deliver(shared)
        original = await open_review(shared, event)
        restarted = TeamsApproval(shared.teams.agent, UUID(TENANT), channel_policy=policy())
        restarted.push_flow = shared.flow
        shared.flow.teams = restarted
        shared.teams = restarted
        reopened = await open_review(shared, event, SECOND, "new-session-after-deployment")
        assert button(reopened, "Approve") == button(original, "Approve")
        await decide(shared, button(reopened, "Approve"), SECOND, "new-session-after-deployment")
        shared.connection.invoke_once.assert_awaited_once()
        # Registration does not require the old registrar's platform session.
        shared.notify.return_value = shared.scope.model_copy(update={"thread_id": "next-review-thread"})
        with platform(CALLER, "another-pipeline-session"):
            notification = await shared.flow.process(push("b" * 40, 101).model_copy(update={"pull_request_id": 13}))
        assert notification["state"] == "notified"

    asyncio.run(run())


def test_notification_missing_thread_is_unknown_and_not_resent(shared):
    async def run():
        shared.notify.return_value = None
        with platform():
            await shared.flow.register(channel_activity(text="enable notifications"))
        with platform(CALLER), pytest.raises(ValueError, match="verified review thread"):
            await shared.flow.process(push().model_copy(update={"pull_request_id": 12}))
        with platform(CALLER), pytest.raises(ValueError, match="incomplete"):
            await shared.flow.process(push().model_copy(update={"pull_request_id": 12}))
        shared.notify.assert_awaited_once()

    asyncio.run(run())


def test_policy_startup_and_channel_identity_are_fail_closed(monkeypatch):
    monkeypatch.setenv("DOCUMENTATION_ENABLE_CHANNEL_REVIEWS", "true")
    monkeypatch.delenv("DOCUMENTATION_TEAMS_CHANNEL_POLICY", raising=False)
    with pytest.raises(ValueError, match="CHANNEL_POLICY"):
        TeamsChannelPolicy.from_environment()
    with pytest.raises(ValueError):
        TeamsChannelPolicy(tenant_id=TENANT, team_id=TEAM, channel_id=CHANNEL, reviewer_aad_ids=[])
    with pytest.raises(ValueError, match="unique"):
        TeamsChannelPolicy(tenant_id=TENANT, team_id=TEAM, channel_id=CHANNEL, reviewer_aad_ids=[USER, USER])
    for field in ("team", "channel", "tenant"):
        message = channel_activity()
        del message.channel_data[field]
        with pytest.raises(ValueError, match="missing"):
            policy().scope(message)
    monkeypatch.setenv("DOCUMENTATION_ENABLE_CHANNEL_REVIEWS", "false")
    assert TeamsChannelPolicy.from_environment() is None


@pytest.mark.parametrize("membership_mode", [False, True])
def test_http_channel_thread_delivery_two_reviewer_flow_and_mentions(shared, tmp_path, monkeypatch, membership_mode):
    async def run():
        config = tmp_path / "push.json"
        config.write_text(shared.flow.policy.model_dump_json())
        env = {
            "DOCUMENTATION_ENABLE_TEAMS": "true", "DOCUMENTATION_TEAMS_TENANT_ID": TENANT,
            "DOCUMENTATION_ENABLE_PUSH_FLOW": "true", "DOCUMENTATION_PUSH_POLICY": str(config),
            "DOCUMENTATION_PUSH_READ_TOOLBOX": (
                "https://test.services.ai.azure.com/api/projects/test/toolboxes/read/versions/1/mcp?api-version=v1"
            ),
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "TOOLBOX_ENDPOINT": shared.teams.agent.policy.toolbox_endpoint, "AZURE_AI_MODEL_DEPLOYMENT_NAME": "test",
            "DOCUMENTATION_MODEL_VERSION": "test", "DOCUMENTATION_ADO_PROJECT": "project",
            "DOCUMENTATION_ADO_WIKI": "wiki", "DOCUMENTATION_ADO_ORGANIZATION": "test",
        }
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr("documentation_agent.assessment.AssessmentAgent", lambda settings: shared.assessor)
        monkeypatch.setattr(
            "documentation_agent.wiki_drafts.WikiDraftPublisher", lambda *args: shared.flow.wiki_publisher,
        )
        service, runner = conversation()
        channel_policy = policy()
        if membership_mode:
            channel_policy = TeamsChannelPolicy(
                tenant_id=TENANT, team_id=TEAM, channel_id=CHANNEL, reviewer_mode="channel_members",
            )
        checks = []

        async def verified_member(self, context, binding):
            assert self.binding(context.activity) == binding
            checks.append(binding.aad_object_id)

        monkeypatch.setattr(TeamsApproval, "verify_member", verified_member)
        post = AsyncMock()
        monkeypatch.setattr("documentation_agent.channel_delivery.create_channel_post", post)
        monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT")
        host = create_teams_server(shared.teams.agent, conversation=service, channel_policy=channel_policy)
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        monkeypatch.setenv("FOUNDRY_AGENT_INSTANCE_CLIENT_ID", "test-bot")
        sent, created = [], []

        async def send(context, messages):
            sent.extend(messages)
            return [ResourceResponse(id="sent") for _ in messages]

        async def new_thread(context, scope, output):
            assert scope.channel_id == CHANNEL and scope.team_id == TEAM
            created.append(scope)
            sent.append(Activity(type="message", attachments=[
                {"contentType": "application/vnd.microsoft.card.adaptive", "content": output},
            ]))
            return scope.model_copy(update={"conversation_id": CHANNEL, "thread_id": THREAD})

        async def proactive(app_id, activity, callback):
            assert app_id == "test-bot"
            await callback(SimpleNamespace(activity=activity))

        monkeypatch.setattr(host.adapter, "send_activities", send)
        post.side_effect = new_thread
        continued = AsyncMock(side_effect=proactive)
        monkeypatch.setattr(host.adapter, "continue_conversation", continued)
        reviewer = {"x-agent-user-id": USER, "x-agent-foundry-call-id": "opaque", "x-agent-session-id": "reviewer-one"}
        second = {**reviewer, "x-agent-user-id": SECOND, "x-agent-session-id": "reviewer-two"}
        pipeline = {**reviewer, "x-agent-user-id": CALLER, "x-agent-session-id": "pipeline"}

        def body(message):
            return message.model_dump(mode="json", by_alias=True, exclude_none=True)

        async with AsyncClient(transport=ASGITransport(app=host), base_url="http://localhost") as client:
            register = channel_activity(text="<at>Bot</at> enable notifications", thread="registration")
            register = Activity.model_validate({
                **body(register), "entities": [
                    {"type": "mention", "mentioned": {"id": "bot", "name": "Bot"}, "text": "<at>Bot</at>"},
                ],
            })
            response = await client.post("/activity/messages", headers=reviewer, json=body(register))
            assert response.status_code == 202
            assert "connected" in json.dumps(sent[-1].attachments[0].content)
            await client.post("/activity/messages", headers=reviewer, json=body(
                channel_activity(text="help", thread="registration"),
            ))
            onboarding = sent[-1].attachments[0].content
            enabled = button(onboarding, "Enable channel notifications")
            clicked = channel_activity(value=enabled, thread="registration")
            clicked.reply_to_id = "help-card-message"
            await client.post("/activity/messages", headers=reviewer, json=body(
                clicked,
            ))
            assert "connected" in json.dumps(sent[-1].attachments[0].content)
            notified = await client.post("/invocations", headers=pipeline, json=push().model_copy(
                update={"pull_request_id": 12},
            ).model_dump(mode="json"))
            assert notified.status_code == 200, notified.text
            assert notified.json()["state"] == "notified"
            assert len(created) == 1
            continued.assert_awaited_once()
            notice = sent[-1].attachments[0].content
            review = await client.post("/activity/messages", headers=reviewer, json=body(
                channel_activity(value=button(notice, "Review")),
            ))
            assert review.status_code == 202
            pending = sent[-1].attachments[0].content
            assert sent[-1].reply_to_id == THREAD
            question = channel_activity(text="<at>Bot</at> explain this draft", user=SECOND)
            question = Activity.model_validate({
                **body(question), "entities": [
                    {"type": "mention", "mentioned": {"id": "bot", "name": "Bot"}, "text": "<at>Bot</at>"},
                ],
            })
            await client.post("/activity/messages", headers=second, json=body(question))
            assert sent[-1].text == "Read-only thread explanation."
            assert sent[-1].reply_to_id == THREAD
            assert runner.reply.call_args.args[0][-1].text.strip() == "explain this draft"
            assert len(runner.reply.call_args.args[2].request.context.wiki_page_paths) == 3
            approved = await client.post("/activity/messages", headers=second, json=body(
                channel_activity(value=button(pending, "Approve"), user=SECOND),
            ))
            assert approved.status_code == 202
            assert "succeeded" in json.dumps(sent[-1].attachments[0].content)
            assert SECOND in json.dumps(sent[-1].attachments[0].content)
            shared.connection.invoke_once.assert_awaited_once()
            await client.post("/activity/messages", headers=reviewer, json=body(
                channel_activity(value=button(pending, "Approve")),
            ))
            assert "succeeded" in json.dumps(sent[-1].attachments[0].content)
            shared.connection.invoke_once.assert_awaited_once()
            assert bool(checks) == membership_mode
            if membership_mode:
                assert checks.count(UUID(SECOND)) >= 3  # initial action, native authorization, pre-claim recheck

    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "changed-draft", "changed-page", "duplicate", "delivery-error"])
def test_explicit_notification_retry_reuses_existing_draft_once(shared, fault):
    async def run():
        from documentation_agent.push_flow import event_key

        shared.notify.side_effect = ValueError("Teams HTTP 400")
        with pytest.raises(ValueError, match="HTTP 400"):
            await deliver(shared)
        event = UUID(event_key(shared.flow.policy, "a" * 40))
        shared.notify.side_effect = None
        if fault == "changed-draft":
            path = next(iter(shared.pages))
            shared.pages[path] = page_snapshot("Changed", path)
        elif fault == "changed-page":
            shared.current[0] = page_snapshot("Changed target")
        elif fault == "delivery-error":
            shared.notify.side_effect = TimeoutError("Outcome unknown")
        with platform():
            command = shared.flow.retry_channel_notification(
                channel_activity(text="retry notification " + str(event)), event,
            )
            if fault in {"changed-draft", "changed-page"}:
                with pytest.raises(ValueError, match="changed"):
                    await command
                assert shared.notify.await_count == 1
            elif fault == "delivery-error":
                with pytest.raises(TimeoutError):
                    await command
            else:
                assert "Review notification posted" in json.dumps(await command)
            if fault in {None, "duplicate", "delivery-error"}:
                with pytest.raises(ValueError, match="not eligible"):
                    await shared.flow.retry_channel_notification(channel_activity(), event)
                assert shared.notify.await_count == 2
        shared.assessor.assess.assert_awaited_once()
        shared.flow.wiki_publisher.publish.assert_awaited_once()
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


def use_member_rule(shared):
    shared.teams.channels = ChannelReviews(shared.teams, TeamsChannelPolicy(
        tenant_id=TENANT, team_id=TEAM, channel_id=CHANNEL, reviewer_mode="channel_members",
    ))


def test_any_verified_channel_member_can_decide_with_audit(shared):
    async def run():
        use_member_rule(shared)
        check = AsyncMock()
        event = await deliver(shared, check)
        card = await open_review(shared, event)
        result = await decide(shared, button(card, "Approve"), VIEWER, "member-session", check)
        assert "succeeded" in json.dumps(result)
        record = (await shared.stores[CHANNEL_STORE].get_item(button(card, "Approve")["pending_id"])).value
        assert record["decided_by_aad_id"] == VIEWER
        assert record["membership_checked_at"]
        assert check.await_count == 4  # registration plus three decision checks
        assert check.call_args.args[0].aad_object_id == UUID(VIEWER)

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["missing-check", "removed", "unavailable", "removed-before-claim"])
def test_membership_failure_prevents_dispatch_including_after_tool_checks(shared, failure):
    async def run():
        use_member_rule(shared)
        event = await deliver(shared, AsyncMock())
        card = await open_review(shared, event)
        check = None if failure == "missing-check" else AsyncMock()
        error = ValueError if failure != "unavailable" else TimeoutError
        if failure == "removed-before-claim":
            check.side_effect = [None, None, ValueError("Member removed before claim")]
        elif check is not None:
            check.side_effect = error("Membership unavailable")
        with pytest.raises(error):
            await decide(shared, button(card, "Approve"), VIEWER, member_check=check)
        shared.connection.invoke_once.assert_not_called()
        record = (await shared.stores[CHANNEL_STORE].get_item(button(card, "Approve")["pending_id"])).value
        assert record["status"] == "pending"

    asyncio.run(run())


def test_member_rule_registration_and_modify_require_current_membership(shared):
    async def run():
        use_member_rule(shared)
        with platform(), pytest.raises(ValueError, match="membership lookup"):
            await shared.flow.register(channel_activity(text="enable notifications"))
        assert await shared.stores[STORE].get_item(shared.flow.recipient_key()) is None
        event = await deliver(shared, AsyncMock())
        card = await open_review(shared, event)
        edit = await decide(shared, button(card, "Modify"), VIEWER, member_check=AsyncMock())
        check = AsyncMock(side_effect=[None, ValueError("Member removed")])
        with pytest.raises(ValueError, match="Member removed"):
            await decide(shared, {
                **button(edit, "New proposal"), "content": "# Revision", "feedback": "Clarify",
            }, VIEWER, member_check=check)
        assert len(shared.pages) == 2
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("failure", [None, "wrong-aad", "wrong-sender", "missing-aad", "not-member", "timeout"])
def test_bot_connector_verifies_exact_live_sender_record(shared, failure):
    async def run():
        from microsoft_agents.activity import ChannelAccount
        from microsoft_agents.activity.teams import ChannelInfo
        from microsoft_agents.hosting.core.connector import ConnectorClientBase, TeamsConnectorClient

        item = channel_activity(user=VIEWER)
        member = ChannelAccount(
            id="foreign" if failure == "wrong-sender" else item.from_property.id,
            aad_object_id=None if failure == "missing-aad" else (SECOND if failure == "wrong-aad" else VIEWER),
        )
        lookup = AsyncMock(return_value=member)
        if failure in {"not-member", "timeout"}:
            lookup.side_effect = (
                ValueError("Member not found") if failure == "not-member" else TimeoutError("No roster")
            )
        connector = Mock(spec=TeamsConnectorClient)
        connector.conversations = SimpleNamespace(get_conversation_member=lookup)
        connector.fetch_channel_list = AsyncMock(return_value=[ChannelInfo(id=CHANNEL, type="standard")])

        def get(kind):
            assert kind is ConnectorClientBase
            return connector

        context = SimpleNamespace(activity=item, services=SimpleNamespace(get=get))
        with platform(VIEWER):
            binding = shared.teams.binding(item)
            if failure:
                with pytest.raises((ValueError, TimeoutError)):
                    await shared.teams.verify_member(context, binding)
            else:
                await shared.teams.verify_member(context, binding)
            lookup.assert_awaited_once_with(item.conversation.id, item.from_property.id)

    asyncio.run(run())


def test_user_link_group_id_binds_signed_channel_context():
    group_id = "00000000-0000-4000-8000-000000000010"
    scoped = TeamsChannelPolicy(
        tenant_id=TENANT, team_aad_group_id=group_id, channel_id=CHANNEL, reviewer_mode="channel_members",
    )
    item = channel_activity()
    with pytest.raises(ValueError, match="outside"):
        scoped.scope(item)
    item.channel_data["team"]["aadGroupId"] = group_id
    scope = scoped.scope(item)
    assert scope.team_id == TEAM and scope.team_aad_group_id == UUID(group_id)
    item.channel_data["team"]["aadGroupId"] = SECOND
    with pytest.raises(ValueError, match="outside"):
        scoped.scope(item)


def test_card_reply_id_can_differ_from_thread_root_without_rebinding():
    root = channel_activity()
    callback = channel_activity()
    callback.reply_to_id = "the-bot-card-message"
    assert policy().scope(callback) == policy().scope(root)
    callback.conversation.id = CHANNEL + ";messageid=another-root"
    assert policy().scope(callback) != policy().scope(root)


@pytest.mark.parametrize("kind", [None, "private", "shared"])
def test_membership_checks_never_authorize_an_unverified_channel_type(shared, kind):
    async def run():
        from microsoft_agents.activity.teams import ChannelInfo
        from microsoft_agents.hosting.core.connector import TeamsConnectorClient

        connector = Mock(spec=TeamsConnectorClient)
        connector.fetch_channel_list = AsyncMock(return_value=[ChannelInfo(id=CHANNEL, type=kind)])
        connector.conversations = SimpleNamespace(get_conversation_member=AsyncMock())
        item = channel_activity()
        context = SimpleNamespace(activity=item, services=SimpleNamespace(get=lambda _: connector))
        with platform(), pytest.raises(ValueError, match="verified standard"):
            await shared.teams.verify_member(context, shared.teams.binding(item))
        connector.conversations.get_conversation_member.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "group", "team", "missing-connector", "lookup-error", "wrong-channel"])
def test_missing_group_id_resolves_only_from_authenticated_teams_metadata(shared, fault):
    async def run():
        from microsoft_agents.activity.teams import TeamDetails
        from microsoft_agents.hosting.core.connector import TeamsConnectorClient

        group = "00000000-0000-4000-8000-000000000010"
        shared.teams.channels = ChannelReviews(shared.teams, TeamsChannelPolicy(
            tenant_id=TENANT, team_aad_group_id=group, channel_id=CHANNEL, reviewer_mode="channel_members",
        ))
        item = channel_activity()
        if fault == "wrong-channel":
            item.channel_data["channel"]["id"] = "another-channel"
        connector = Mock(spec=TeamsConnectorClient)
        connector.fetch_team_details = AsyncMock(return_value=TeamDetails(
            id="another-team" if fault == "team" else TEAM,
            aad_group_id=SECOND if fault == "group" else group,
        ))
        if fault == "lookup-error":
            connector.fetch_team_details.side_effect = TimeoutError("Team lookup unavailable")
        context = SimpleNamespace(
            activity=item, services=SimpleNamespace(get=lambda _: None if fault == "missing-connector" else connector),
        )
        with platform():
            if fault:
                with pytest.raises((ValueError, TimeoutError)):
                    await shared.teams.resolve_channel_team(context)
                assert "aadGroupId" not in item.channel_data["team"]
            else:
                await shared.teams.resolve_channel_team(context)
                assert shared.teams.binding(item).shared_scope.team_aad_group_id == UUID(group)
            if fault in {"wrong-channel", "missing-connector"}:
                connector.fetch_team_details.assert_not_called()
            else:
                connector.fetch_team_details.assert_awaited_once_with(TEAM)
        # A conflicting signed field is never silently replaced by a lookup.
        item = channel_activity()
        item.channel_data["team"]["aadGroupId"] = SECOND
        context.activity = item
        connector.fetch_team_details.reset_mock()
        with platform():
            await shared.teams.resolve_channel_team(context)
            with pytest.raises(ValueError, match="outside"):
                shared.teams.binding(item)
        connector.fetch_team_details.assert_not_called()

    asyncio.run(run())
