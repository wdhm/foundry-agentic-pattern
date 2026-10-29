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


def test_actual_sdk_durable_task_runs_after_submission(shared, monkeypatch):
    from azure.ai.agentserver.core import AgentServerHost
    from azure.ai.agentserver.core.tasks import set_resilient_tasks_enabled
    from documentation_agent.channel_jobs import register_decision_task

    async def run():
        event = await deliver(shared)
        review = await open_review(shared, event)
        jobs, sent = job_harness(shared)
        monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT")
        work = register_decision_task(jobs)
        host = AgentServerHost()
        try:
            async with host.router.lifespan_context(host):
                monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "true")
                with platform():
                    ack = await jobs.enqueue(channel_activity(value=button(review, "Approve")), work.start)
                assert "Decision received" in json.dumps(ack)
                for _ in range(100):
                    record = await shared.stores[STORE].get_item(
                        "decision-" + button(review, "Approve")["pending_id"],
                    )
                    if record.value["state"] in {"completed", "needs_reconciliation"}:
                        break
                    await asyncio.sleep(0.05)
                assert record.value["state"] == "completed"
                shared.connection.invoke_once.assert_awaited_once()
                assert len(sent) == 1
        finally:
            set_resilient_tasks_enabled(False)

    asyncio.run(run())
