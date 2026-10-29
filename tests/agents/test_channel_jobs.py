import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from documentation_agent.channel_jobs import STORE, ChannelDecisionJobs
from test_channel_reviews import (
    SECOND,
    USER,
    VIEWER,
    button,
    channel_activity,
    deliver,
    open_review,
    platform,
    use_member_rule,
)
from test_channel_reviews import shared as shared
from test_push_flow import harness as harness


def job_harness(shared):
    sent = []
    contexts = []

    class Context:
        def __init__(self, activity):
            self.activity = activity
            self.hook = None

        def on_send_activities(self, hook):
            self.hook = hook

        async def send_activity(self, activity):
            async def send():
                sent.append(activity)
                return []
            if self.hook:
                await self.hook(self, [activity], send)
            else:
                await send()

    async def continued(app_id, activity, callback):
        assert app_id == "bot"
        context = Context(activity)
        contexts.append(context)
        await callback(context)

    adapter = SimpleNamespace(continue_conversation=AsyncMock(side_effect=continued))
    return ChannelDecisionJobs(shared.teams, adapter, "bot"), sent


@pytest.mark.parametrize("verb,expected", [("Approve", "succeeded"), ("Reject", "rejected")])
def test_ack_precedes_external_work_and_worker_preserves_actual_actor(shared, monkeypatch, verb, expected):
    async def run():
        event = await deliver(shared)
        review = await open_review(shared, event)
        use_member_rule(shared)
        jobs, sent = job_harness(shared)
        submit = AsyncMock()
        member = AsyncMock()
        monkeypatch.setattr(shared.teams, "verify_saved_member", member)
        with platform(SECOND, "second"):
            ack = await jobs.enqueue(channel_activity(value=button(review, verb), user=SECOND), submit)
        assert "Decision received" in json.dumps(ack)
        assert "Published" not in json.dumps(ack)
        shared.connection.invoke_once.assert_not_called()
        with platform(SECOND, "second"):
            queued = await jobs.status(channel_activity(value=ack["actions"][0]["data"], user=SECOND))
            assert [a["title"] for a in queued["actions"]] == ["Refresh status"]
        job_id = submit.call_args.kwargs["input"]
        assert submit.call_args.kwargs["task_id"] == job_id
        # No platform-user impersonation required when the durable worker resumes.
        await jobs.execute(job_id)
        assert len(sent) == 1 and expected in json.dumps(sent[0].attachments[0].content)
        if verb == "Approve":
            shared.connection.invoke_once.assert_awaited_once()
        else:
            shared.connection.invoke_once.assert_not_called()
        assert member.call_args.args[1].aad_object_id.hex == SECOND.replace("-", "")
        await jobs.execute(job_id)  # simulated recovered task cannot replay
        assert len(sent) == 1
        assert (await shared.stores[STORE].get_item(job_id)).value["state"] == "completed"

    asyncio.run(run())


def test_enqueue_does_not_wait_for_the_slow_write(shared, monkeypatch):
    async def run():
        event = await deliver(shared)
        review = await open_review(shared, event)
        jobs, _ = job_harness(shared)
        submit = AsyncMock()
        started = asyncio.Event()
        release = asyncio.Event()
        original = shared.connection.invoke_once.side_effect

        async def slow(arguments):
            started.set()
            await release.wait()
            return await original(arguments)

        shared.connection.invoke_once.side_effect = slow
        with platform():
            await asyncio.wait_for(jobs.enqueue(channel_activity(value=button(review, "Approve")), submit), timeout=2)
        assert not started.is_set()
        worker = asyncio.create_task(jobs.execute(submit.call_args.kwargs["input"]))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            assert not worker.done()
        finally:
            release.set()
        await worker
        shared.connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_queue_failure_is_not_success_and_duplicate_does_not_replace_saved_actor(shared):
    async def run():
        event = await deliver(shared)
        review = await open_review(shared, event)
        jobs, _ = job_harness(shared)
        submit = AsyncMock(side_effect=ConnectionError("Task service down"))
        with platform(), pytest.raises(ConnectionError):
            await jobs.enqueue(channel_activity(value=button(review, "Approve")), submit)
        submit.side_effect = None
        with platform(SECOND, "second"):
            await jobs.enqueue(channel_activity(value=button(review, "Reject"), user=SECOND), submit)
        saved = (await shared.stores[STORE].get_item(submit.call_args.kwargs["task_id"])).value
        assert saved["binding"]["owner"] == USER
        assert saved["submitted"]["action"] == "approve"
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["membership", "write", "delivery"])
def test_failed_worker_never_replays_or_claims_success(shared, monkeypatch, failure):
    async def run():
        event = await deliver(shared)
        review = await open_review(shared, event)
        jobs, sent = job_harness(shared)
        member = AsyncMock(side_effect=ValueError("Removed") if failure == "membership" else None)
        monkeypatch.setattr(shared.teams, "verify_saved_member", member)
        # Membership mode enforces the injected current-roster check.
        use_member_rule(shared)
        if failure == "write":
            shared.connection.invoke_once.side_effect = TimeoutError("Unknown write outcome")
        if failure == "delivery":
            jobs.adapter.continue_conversation.side_effect = ConnectionError("Cannot start authenticated continuation")
        submit = AsyncMock()
        with platform():
            await jobs.enqueue(channel_activity(value=button(review, "Approve")), submit)
        job_id = submit.call_args.kwargs["input"]
        with pytest.raises((ValueError, TimeoutError, ConnectionError)):
            await jobs.execute(job_id)
        assert (await shared.stores[STORE].get_item(job_id)).value["state"] == "needs_reconciliation"
        attempts = shared.connection.invoke_once.await_count
        await jobs.execute(job_id)
        assert shared.connection.invoke_once.await_count == attempts
        if failure == "delivery":
            assert not sent
        else:
            assert len(sent) == 1 and "Decision needs attention" in json.dumps(sent[0].attachments[0].content)

    asyncio.run(run())


def test_unknown_job_and_unauthorized_queue_are_rejected(shared):
    async def run():
        jobs, _ = job_harness(shared)
        with pytest.raises(ValueError, match="no authenticated"):
            await jobs.execute("arbitrary")
        event = await deliver(shared)
        review = await open_review(shared, event)
        with platform(VIEWER), pytest.raises(ValueError, match="not an authorized"):
            await jobs.enqueue(channel_activity(value=button(review, "Approve"), user=VIEWER), AsyncMock())
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("opening", [False, True])
def test_actual_sdk_durable_task_runs_after_submission(shared, monkeypatch, opening):
    from azure.ai.agentserver.core.tasks import set_resilient_tasks_enabled
    from documentation_agent.channel_jobs import register_decision_task
    from documentation_agent.teams import PushTeamsHost

    async def run():
        event = await deliver(shared)
        review = None if opening else await open_review(shared, event)
        jobs, sent = job_harness(shared)
        monkeypatch.setattr(shared.teams, "verify_saved_member", AsyncMock())
        monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT")
        host = PushTeamsHost(agent=shared.teams.agent, history_source="agent")
        work = register_decision_task(jobs)
        try:
            async with host.router.lifespan_context(host):
                monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
                with platform():
                    if opening:
                        ack = await jobs.enqueue_review(channel_activity(value=review_value(event)), work.start)
                        job_id = "review-" + str(event)
                    else:
                        ack = await jobs.enqueue(channel_activity(value=button(review, "Approve")), work.start)
                        job_id = "decision-" + button(review, "Approve")["pending_id"]
                assert ("Opening review" if opening else "Decision received") in json.dumps(ack)
                for _ in range(100):
                    record = await shared.stores[STORE].get_item(job_id)
                    if record.value["state"] in {"completed", "needs_reconciliation"}:
                        break
                    await asyncio.sleep(0.05)
                assert record.value["state"] == "completed"
                assert shared.connection.invoke_once.await_count == (0 if opening else 1)
                assert len(sent) == 1
        finally:
            set_resilient_tasks_enabled(False)

    asyncio.run(run())


def review_value(event):
    return {"interface_version": "1.0.0", "action": "review_push", "event_id": str(event)}


def test_review_ack_does_not_wait_for_preparation_and_two_users_share_one_job(shared, monkeypatch):
    async def run():
        from documentation_agent.push_flow import STORE as EVENT_STORE

        event = await deliver(shared)
        jobs, sent = job_harness(shared)
        submit = AsyncMock()
        member = AsyncMock()
        monkeypatch.setattr(shared.teams, "verify_saved_member", member)
        original = shared.flow.open_saved_channel_review
        started, release = asyncio.Event(), asyncio.Event()

        async def slow(*args):
            started.set()
            await release.wait()
            return await original(*args)

        monkeypatch.setattr(shared.flow, "open_saved_channel_review", slow)
        with platform():
            ack = await asyncio.wait_for(
                jobs.enqueue_review(channel_activity(value=review_value(event)), submit), timeout=2,
            )
        assert "Opening review" in str(ack) and not started.is_set()
        assert (await shared.stores[EVENT_STORE].get_item(str(event))).value["state"] == "notified"
        job_id = submit.call_args.kwargs["task_id"]
        worker = asyncio.create_task(jobs.execute(job_id))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            with platform(SECOND, "other-session"):
                duplicate = await jobs.enqueue_review(
                    channel_activity(value=review_value(event), user=SECOND), submit,
                )
            assert "Opening review" in str(duplicate)
            submit.assert_awaited_once()
        finally:
            release.set()
        await worker
        assert len(sent) == 1
        assert sent[0].reply_to_id == shared.scope.thread_id
        assert [a["title"] for a in sent[0].attachments[0].content["actions"]] == ["Approve", "Modify", "Reject"]
        assert member.call_args.args[1].owner == USER
        with platform(SECOND):
            assert "Review card sent" in str(await jobs.enqueue_review(
                channel_activity(value=review_value(event), user=SECOND), submit,
            ))
        await jobs.execute(job_id)  # recovery must not send another card
        assert len(sent) == 1
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("fault", [
    "foreign-thread", "malformed", "queue-down", "removed", "superseded", "send-failure",
])
def test_queued_review_failures_never_authorize_publication(shared, monkeypatch, fault):
    async def run():
        from documentation_agent.push_flow import STORE as EVENT_STORE

        event = await deliver(shared)
        jobs, sent = job_harness(shared)
        submit, member = AsyncMock(), AsyncMock()
        monkeypatch.setattr(shared.teams, "verify_saved_member", member)
        value = review_value(event)
        activity = channel_activity(
            value=value, thread="different" if fault == "foreign-thread" else shared.scope.thread_id,
        )
        if fault == "malformed":
            activity.value = {**value, "approve": True}
        if fault == "queue-down":
            submit.side_effect = ConnectionError("Task service down")
        with platform():
            if fault in {"foreign-thread", "malformed", "queue-down"}:
                with pytest.raises((ValueError, ConnectionError)):
                    await jobs.enqueue_review(activity, submit)
                shared.connection.invoke_once.assert_not_called()
                return
            await jobs.enqueue_review(activity, submit)
        job_id = submit.call_args.kwargs["task_id"]
        if fault == "removed":
            member.side_effect = ValueError("No longer a member")
        elif fault == "superseded":
            latest = await shared.stores[EVENT_STORE].get_item("latest")
            await shared.stores[EVENT_STORE].set_item(
                "latest", {"event_id": "newer", "build_id": 999}, if_match=latest.etag,
            )
        else:
            jobs.adapter.continue_conversation.side_effect = ConnectionError("Delivery failed")
        with pytest.raises((ValueError, ConnectionError)):
            await jobs.execute(job_id)
        state = (await shared.stores[STORE].get_item(job_id)).value
        assert state["state"] == "needs_reconciliation"
        assert len(sent) == (0 if fault == "send-failure" else 1)
        if sent:
            assert "Review needs attention" in str(sent[0].attachments[0].content)
        await jobs.execute(job_id)
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
def test_http_review_uses_opt_in_queue_without_waiting_for_proposal(shared, tmp_path, monkeypatch, enabled):
    from documentation_agent.push_flow import PushFlow
    from documentation_agent.teams import create_teams_server
    from httpx import ASGITransport, AsyncClient
    from microsoft_agents.activity import ResourceResponse
    from test_channel_reviews import TENANT

    async def run():
        event = await deliver(shared)
        config = tmp_path / "push.json"
        config.write_text(shared.flow.policy.model_dump_json())
        for key, value in {
            "DOCUMENTATION_ENABLE_TEAMS": "true", "DOCUMENTATION_TEAMS_TENANT_ID": TENANT,
            "DOCUMENTATION_ENABLE_PUSH_FLOW": "true", "DOCUMENTATION_PUSH_POLICY": str(config),
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "DOCUMENTATION_PUSH_READ_TOOLBOX": (
                "https://test.services.ai.azure.com/api/projects/test/toolboxes/read/versions/1/mcp?api-version=v1"
            ),
            "TOOLBOX_ENDPOINT": shared.teams.agent.policy.toolbox_endpoint,
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "test", "DOCUMENTATION_MODEL_VERSION": "test",
            "DOCUMENTATION_ADO_PROJECT": "project", "DOCUMENTATION_ADO_WIKI": "wiki",
            "DOCUMENTATION_ADO_ORGANIZATION": "test",
            "DOCUMENTATION_ENABLE_DURABLE_DECISIONS": "true" if enabled else "false",
        }.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr("documentation_agent.assessment.AssessmentAgent", lambda _: shared.assessor)
        monkeypatch.setattr("documentation_agent.wiki_drafts.WikiDraftPublisher",
                            lambda *args: shared.flow.wiki_publisher)
        queued = AsyncMock()
        registered = []

        def register(jobs):
            registered.append(jobs)
            return SimpleNamespace(start=queued)

        monkeypatch.setattr("documentation_agent.channel_jobs.register_decision_task", register)
        # Supply the job identity without configuring real outbound auth in the local host.
        original_jobs = ChannelDecisionJobs
        monkeypatch.setattr("documentation_agent.channel_jobs.ChannelDecisionJobs",
                            lambda handler, adapter, app_id: original_jobs(handler, adapter, "bot"))
        monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT")
        host = create_teams_server(shared.teams.agent, channel_policy=shared.teams.channels.policy)
        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
        sent = []

        async def send(context, activities):
            sent.extend(activities)
            return [ResourceResponse(id="sent") for _ in activities]

        monkeypatch.setattr(host.adapter, "send_activities", send)
        if enabled:
            monkeypatch.setattr(PushFlow, "_open_review", AsyncMock(side_effect=AssertionError("Must not wait here")))
        headers = {"x-agent-user-id": USER, "x-agent-foundry-call-id": "call", "x-agent-session-id": "http-session"}
        body = channel_activity(value=review_value(event)).model_dump(mode="json", by_alias=True, exclude_none=True)
        async with AsyncClient(transport=ASGITransport(app=host), base_url="http://localhost") as client:
            response = await client.post("/activity/messages", json=body, headers=headers)
        assert response.status_code == 202
        if enabled:
            queued.assert_awaited_once_with(task_id="review-" + str(event), input="review-" + str(event))
            assert "Opening review" in str(sent[-1].attachments[0].content)
            assert len(registered) == 1
        else:
            queued.assert_not_called()
            assert "Review documentation draft" in str(sent[-1].attachments[0].content)
            assert not registered
        shared.connection.invoke_once.assert_not_called()

    asyncio.run(run())
