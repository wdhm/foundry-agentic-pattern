"""Opt-in durable acknowledgement for channel reviews/decisions; never replay a claimed job."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from azure.ai.agentserver.core.storage import FoundryStateStore, FoundryStorageConflictError
from azure.ai.agentserver.core.tasks import (
    RetryPolicy,
    TaskConflictError,
    TaskContext,
    set_resilient_tasks_enabled,
    task,
)
from microsoft_agents.activity import Activity, Attachment
from microsoft_agents.hosting.core import TurnContext

from .teams import CardAction, ChannelBinding, TeamsApproval
from .teams_card import CARD_TYPE, action, card, secondary, status_header, text

LOGGER = logging.getLogger(__name__)
STORE = "documentation-channel-decision-jobs-v1"


class ChannelDecisionJobs:
    def __init__(self, handler: TeamsApproval, adapter: Any, app_id: str) -> None:
        if handler.channels is None or not app_id:
            raise ValueError("Durable channel decisions require channel policy and bot identity.")
        self.handler = handler
        self.adapter = adapter
        self.app_id = app_id

    @staticmethod
    def review_progress(state: str) -> dict[str, Any]:
        if state == "completed":
            title, message = "Review card sent", "Use the review card posted in this thread."
        elif state == "needs_reconciliation":
            title, message = "Review needs attention", "The review could not be delivered. Contact the operator."
        else:
            title, message = "Opening review", "The request is saved. The review card will follow in this thread."
        return card([
            status_header("outcome_unknown" if state == "needs_reconciliation" else "pending", title=title),
            text(message), secondary("Opening a review does not publish or approve a wiki update."),
        ])

    async def enqueue_review(self, activity: Activity, submit: Any) -> dict[str, Any]:
        from .push_flow import ReviewAction

        binding = self.handler.binding(activity)
        review = ReviewAction.model_validate(activity.value)
        flow = self.handler.push_flow
        if flow is None:
            raise ValueError("Review workflow unavailable.")
        await flow.check_channel_review(binding, review.event_id)
        job_id = "review-" + str(review.event_id)
        values: dict[str, Any] = {
            "binding": binding.model_dump(mode="json"),
            "activity": activity.model_dump(mode="json", by_alias=True, exclude_none=True),
            "submitted": review.model_dump(mode="json"),
            "state": "queued", "created_at": datetime.now(UTC).isoformat(),
        }
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            try:
                await store.create_item(job_id, values)
            except FoundryStorageConflictError:
                existing = await store.get_item(job_id)
                if existing is None:
                    raise ValueError("Queued review unavailable; inspect saved status.") from None
                saved = ChannelBinding.model_validate(existing.value["binding"])
                if saved.shared_scope != binding.shared_scope:
                    raise ValueError("Queued review belongs to another thread.") from None
                if existing.value["state"] != "queued":
                    return self.review_progress(existing.value["state"])
            try:
                await submit(task_id=job_id, input=job_id)
            except TaskConflictError:
                LOGGER.info("Durable review task already exists for %s.", review.event_id)
            except Exception:
                LOGGER.error("Could not confirm durable review submission for %s.", review.event_id)
                raise
        return self.review_progress("queued")

    async def execute_review(self, job_id: str) -> None:
        from .push_flow import ReviewAction

        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            item = await store.get_item(job_id)
            if item is None:
                raise ValueError("Durable review has no authenticated server-side record.")
            values = item.value
            if values["state"] != "queued":
                LOGGER.warning("Review job %s already claimed; recovery will not replay it.", job_id)
                return
            binding = ChannelBinding.model_validate(values["binding"])
            review = ReviewAction.model_validate(values["submitted"])
            activity = Activity.model_validate(values["activity"])
            if job_id != "review-" + str(review.event_id) or ReviewAction.model_validate(activity.value) != review:
                raise ValueError("Saved review identity or action differs.")
            flow = self.handler.push_flow
            if flow is None or binding.shared_scope is None:
                raise ValueError("Saved review requires the configured channel workflow.")
            values["state"] = "running"
            claimed = await self.handler.agent.replace(store, job_id, values, item.etag)
            try:
                async def process(context: TurnContext) -> None:
                    context.activity.channel_data = activity.channel_data
                    context.activity.from_property = activity.from_property
                    context.activity.conversation = activity.conversation
                    context.activity.reply_to_id = activity.reply_to_id

                    async def root_reply(turn: TurnContext, messages: list[Activity], send: Any) -> Any:
                        for message in messages:
                            if binding.shared_scope is None:
                                raise ValueError("Missing saved review thread.")
                            message.reply_to_id = binding.shared_scope.thread_id
                        return await send()

                    context.on_send_activities(root_reply)
                    try:
                        # Any current channel member may view the review, even
                        # when only an allowlist may later decide it.
                        await self.handler.verify_saved_member(context, binding)
                        output = await flow.open_saved_channel_review(binding, review.event_id)
                    except Exception:
                        await context.send_activity(Activity(type="message", attachments=[
                            Attachment(content_type=CARD_TYPE, content=self.review_progress("needs_reconciliation")),
                        ]))
                        raise
                    await context.send_activity(Activity(type="message", attachments=[
                        Attachment(content_type=CARD_TYPE, content=output),
                    ]))

                await self.adapter.continue_conversation(
                    self.app_id, activity.get_conversation_reference().get_continuation_activity(), process,
                )
                values.update(state="completed", completed_at=datetime.now(UTC).isoformat())
                await self.handler.agent.replace(store, job_id, values, claimed.etag)
            except Exception as exc:
                LOGGER.error("Durable review %s interrupted (%s); no automatic retry.", job_id, type(exc).__name__)
                values.update(state="needs_reconciliation", error_type=type(exc).__name__)
                await self.handler.agent.replace(store, job_id, values, claimed.etag)
                raise

    async def status(self, activity: Activity) -> dict[str, Any]:
        binding = self.handler.binding(activity)
        submitted = CardAction.model_validate(activity.value)
        if self.handler.channels is None or submitted.action != "inspect":
            raise ValueError("Status requires a shared review inspection.")
        pending = await self.handler.channels.record(submitted.pending_id, binding)
        if submitted.args_hash != pending.args_hash:
            raise ValueError("Status card arguments differ from the saved proposal.")
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            item = await store.get_item("decision-" + str(pending.pending_id))
        if item is not None and pending.status == "pending":
            state = item.value["state"]
            uncertain = state in {"running", "needs_reconciliation"}
            return card([
                status_header("outcome_unknown" if uncertain else "executing",
                              title="Decision received — awaiting final result"),
                text("Do not submit another decision. "
                     "If processing has stopped, contact the operator to reconcile it."),
                secondary(f"Job status: {state}"),
            ], [action(pending, "inspect", "Refresh status")])
        return await self.handler.channels.render(pending, binding)

    async def enqueue(self, activity: Activity, submit: Any) -> dict[str, Any]:
        binding = self.handler.binding(activity)
        submitted = CardAction.model_validate(activity.value)
        if submitted.action not in {"approve", "reject", "modify"} or self.handler.channels is None:
            raise ValueError("Only explicit channel decisions can be queued.")
        pending = await self.handler.channels.record(submitted.pending_id, binding)
        self.handler.channels.authorize(binding, pending, decide=True)
        if pending.args_hash != submitted.args_hash:
            raise ValueError("Card arguments differ from the saved proposal.")
        if pending.status != "pending":
            return await self.handler.channels.render(pending, binding)
        # A single job per proposal: retries or competing clicks cannot queue
        # independent decisions. The existing pending-call CAS still gates writes.
        job_id = "decision-" + str(pending.pending_id)
        values: dict[str, Any] = {
            "binding": binding.model_dump(mode="json"),
            "activity": activity.model_dump(mode="json", by_alias=True, exclude_none=True),
            "submitted": submitted.model_dump(mode="json"),
            "state": "queued", "created_at": datetime.now(UTC).isoformat(),
        }
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            try:
                await store.create_item(job_id, values)
            except FoundryStorageConflictError:
                existing = await store.get_item(job_id)
                if existing is None:
                    raise ValueError("Queued decision unavailable; inspect saved status.") from None
                saved = ChannelBinding.model_validate(existing.value["binding"])
                if saved.shared_scope != binding.shared_scope:
                    raise ValueError("Queued decision belongs to another thread.") from None
                if existing.value["state"] != "queued":
                    return card([
                        status_header(
                            "outcome_unknown" if existing.value["state"] == "needs_reconciliation" else "executing",
                            title="Decision already received",
                        ),
                        text("Use Refresh status. If no final result is available, contact the operator. "
                             "Do not submit another decision."),
                    ], [action(pending, "inspect", "Refresh status")])
            try:
                await submit(task_id=job_id, input=job_id)
            except TaskConflictError:
                LOGGER.info("Durable decision task already exists for %s.", pending.pending_id)
            except Exception:
                LOGGER.error(
                    "Could not confirm durable job submission for %s; inspect before retry.", pending.pending_id,
                )
                raise
        return card([
            status_header("executing", title="Decision received — processing"),
            text("The request is saved. Membership and version checks run before any publication."),
            secondary("A result card will follow. Receiving this request is not confirmation of a wiki update."),
        ], [action(pending, "inspect", "Refresh status")])

    async def execute(self, job_id: str) -> None:
        if job_id.startswith("review-"):
            await self.execute_review(job_id)
            return
        store = await FoundryStateStore.get_or_create(STORE, user_isolation=False)
        async with store:
            item = await store.get_item(job_id)
            if item is None:
                raise ValueError("Durable decision has no authenticated server-side record.")
            values = item.value
            if values["state"] != "queued":
                LOGGER.warning("Decision job %s already claimed; recovery will not replay it.", job_id)
                return
            binding = ChannelBinding.model_validate(values["binding"])
            submitted = CardAction.model_validate(values["submitted"])
            activity = Activity.model_validate(values["activity"])
            if (
                job_id != "decision-" + str(submitted.pending_id)
                or submitted.action not in {"approve", "reject", "modify"}
            ):
                raise ValueError("Invalid saved decision job.")
            if CardAction.model_validate(activity.value) != submitted:
                raise ValueError("Saved action and activity disagree.")
            channels = self.handler.channels
            if channels is None:
                raise ValueError("Shared channel runtime unavailable.")
            pending = await channels.record(submitted.pending_id, binding)
            channels.authorize(binding, pending, decide=True)
            # Persist the execution claim before any external operation. A crash
            # here deliberately requires reconciliation instead of auto-replay.
            values["state"] = "running"
            claimed = await self.handler.agent.replace(store, job_id, values, item.etag)
            try:
                async def process(context: TurnContext) -> None:
                    # The saved activity came from the validated inbound handler,
                    # not from the task input. Never set/forge platform user context.
                    context.activity.channel_data = activity.channel_data
                    context.activity.from_property = activity.from_property
                    context.activity.conversation = activity.conversation
                    context.activity.reply_to_id = activity.reply_to_id

                    async def membership(expected: ChannelBinding) -> None:
                        await self.handler.verify_saved_member(context, expected)

                    async def root_reply(turn: TurnContext, messages: list[Activity], send: Any) -> Any:
                        for message in messages:
                            if binding.shared_scope is None:
                                raise ValueError("Missing saved review thread.")
                            message.reply_to_id = binding.shared_scope.thread_id
                        return await send()

                    context.on_send_activities(root_reply)
                    try:
                        output = await channels.handle(submitted, binding, member_check=membership)
                    except Exception:
                        await context.send_activity(Activity(
                            type="message", attachments=[Attachment(content_type=CARD_TYPE, content=card([
                                status_header("outcome_unknown", title="Decision needs attention"),
                                text("The request could not be completed normally. Refresh the saved proposal status "
                                     "and contact the operator before retrying. A write outcome may be uncertain."),
                            ], [action(pending, "inspect", "Refresh status")]))],
                        ))
                        raise
                    # Card only avoids a second Teams activity for the text body.
                    await context.send_activity(Activity(
                        type="message", attachments=[Attachment(content_type=CARD_TYPE, content=output)],
                    ))

                await self.adapter.continue_conversation(
                    self.app_id, activity.get_conversation_reference().get_continuation_activity(), process,
                )
                values["state"] = "completed"
                values["completed_at"] = datetime.now(UTC).isoformat()
                await self.handler.agent.replace(store, job_id, values, claimed.etag)
            except Exception as exc:
                LOGGER.error("Durable decision %s interrupted (%s); no automatic retry.", job_id, type(exc).__name__)
                values.update(state="needs_reconciliation", error_type=type(exc).__name__)
                await self.handler.agent.replace(store, job_id, values, claimed.etag)
                raise


def register_decision_task(jobs: ChannelDecisionJobs) -> Any:
    set_resilient_tasks_enabled(True)

    @task(name="documentation-channel-decision-v1", timeout=timedelta(minutes=5),
          retry=RetryPolicy(max_attempts=1))
    async def process(ctx: TaskContext[str]) -> None:
        if ctx.task_id != ctx.input:
            raise ValueError("Durable decision task identity mismatch.")
        await jobs.execute(ctx.input)

    return process
