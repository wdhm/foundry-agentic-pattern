"""Isolated native-approval experiment. The only write is an atomic dummy receipt."""

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from agent_framework import (
    AgentRunInputs,
    AgentSession,
    Content,
)
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.core.storage import FoundryStateStore
from pydantic import Field, TypeAdapter, ValidationError

from contracts.models import ContractModel, NonBlank
from contracts.v1 import Evidence

from .agent import request_text
from .approval_common import ApprovalAgentBase, approval_decision, canonical_hash

TOOL_NAME = "dummy.write"
STORE_NAME = "documentation-approval-spike-v1"


class DummyArguments(ContractModel):
    run_id: UUID
    page: Literal["/approval-spike"]
    content: Annotated[NonBlank, Field(max_length=4000)]


class Propose(ContractModel):
    action: Literal["propose"]
    arguments: DummyArguments
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=5)]


class Modify(ContractModel):
    action: Literal["modify"]
    pending_id: UUID
    feedback: Annotated[NonBlank, Field(max_length=1000)]
    content: Annotated[NonBlank, Field(max_length=4000)]


class Inspect(ContractModel):
    action: Literal["inspect"]
    pending_id: UUID


Command = Annotated[Propose | Modify | Inspect, Field(discriminator="action")]
COMMAND: TypeAdapter[Propose | Modify | Inspect] = TypeAdapter(Command)


def arguments_hash(arguments: DummyArguments) -> str:
    value = {"tool": TOOL_NAME, "arguments": arguments.model_dump(mode="json")}
    return canonical_hash(value)


def preview(record: dict[str, Any]) -> str:
    evidence = "\n".join(
        f"- {item['source']}: {item['uri']} (version {item['version']})\n  {item['excerpt']}"
        for item in record["evidence"]
    )
    return (
        "APPROVAL SPIKE - fictional proposal; not a wiki write.\n"
        f"Pending ID: {record['pending_id']}\nRun ID: {record['arguments']['run_id']}\n"
        f"Tool: {TOOL_NAME}\nArguments SHA-256: {record['args_hash']}\n"
        f"Exact arguments: {json.dumps(record['arguments'], sort_keys=True)}\n"
        f"Evidence (supplied for this demo, not independently verified):\n{evidence}\n"
        "Approve creates one dummy receipt. Reject creates no receipt. "
        "Modify voids this proposal and requires approval of a new one."
    )


def approval_content(record: dict[str, Any]) -> Content:
    return Content.from_function_approval_request(
        id=record["pending_id"],
        function_call=Content.from_function_call(
            record["call_id"],
            TOOL_NAME,
            arguments=record["arguments"],
            additional_properties={"server_label": "approval_spike"},
        ),
    )


class ApprovalSpikeAgent(ApprovalAgentBase):
    def __init__(self, *, allow_local: bool = False) -> None:
        super().__init__(name="documentation-approval-spike", description="Native approval with a dummy state receipt.")
        self.allow_local = allow_local

    async def execute(self, messages: AgentRunInputs | None, session: AgentSession | None) -> list[Content]:
        if session is None:
            raise ValueError("Approval spike requires a hosting session.")
        actor = self.actor()
        decision = approval_decision(messages)

        store = await FoundryStateStore.get_or_create(STORE_NAME, user_isolation=True)
        async with store:
            if decision is not None:
                return await self.decide(store, decision, actor, session.session_id)
            try:
                command = COMMAND.validate_json(request_text(messages))
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid spike command: {exc.errors(include_input=False, include_url=False)}"
                ) from None
            if isinstance(command, Propose):
                record = self.proposal(command.arguments, command.evidence, actor, session.session_id)
                await store.create_item(record["pending_id"], record)
                return [Content.from_text(preview(record)), approval_content(record)]
            stored = await store.get_item(str(command.pending_id))
            if stored is None:
                raise ValueError("Unknown pending approval.")
            record = stored.value
            self.check_owner(record, actor, session.session_id)
            if isinstance(command, Inspect):
                return [Content.from_text(json.dumps(record, sort_keys=True))]
            self.check_pending(record)
            replacement = DummyArguments.model_validate({**record["arguments"], "content": command.content})
            next_record = self.proposal(
                replacement, [Evidence.model_validate(e) for e in record["evidence"]], actor, session.session_id
            )
            # Invalidate first: if the subsequent create fails, the old call still cannot execute.
            changed = {
                **record,
                "status": "modified",
                "feedback": command.feedback,
                "decided_by": actor,
                "decided_at": datetime.now(UTC).isoformat(),
                "replacement_id": next_record["pending_id"],
            }
            await self.replace(store, record["pending_id"], changed, stored.etag)
            await store.create_item(next_record["pending_id"], next_record)
            return [Content.from_text(preview(next_record)), approval_content(next_record)]

    @staticmethod
    def proposal(arguments: DummyArguments, evidence: list[Evidence], actor: str, session_id: str) -> dict[str, Any]:
        return {
            "pending_id": str(uuid4()),
            "call_id": str(uuid4()),
            "tool": TOOL_NAME,
            "arguments": arguments.model_dump(mode="json"),
            "args_hash": arguments_hash(arguments),
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "status": "pending",
            "owner": actor,
            "session_id": session_id,
            "created_at": datetime.now(UTC).isoformat(),
        }

    async def decide(self, store: FoundryStateStore, decision: Content, actor: str, session_id: str) -> list[Content]:
        if not isinstance(decision.id, str) or type(decision.approved) is not bool:
            raise ValueError("Malformed native approval response.")
        item = await store.get_item(str(UUID(decision.id)))
        if item is None:
            raise ValueError("Unknown approval request.")
        record = item.value
        self.check_owner(record, actor, session_id)
        self.check_pending(record)
        call = decision.function_call
        if call is None or call.name != TOOL_NAME or call.call_id != record["call_id"]:
            raise ValueError("Approval does not match the pending tool call.")
        supplied = (
            DummyArguments.model_validate_json(call.arguments)
            if isinstance(call.arguments, str)
            else DummyArguments.model_validate(call.arguments)
        )
        if arguments_hash(supplied) != record["args_hash"] or supplied.model_dump(mode="json") != record["arguments"]:
            raise ValueError("Approval arguments were changed; decision rejected.")
        changed = {
            **record,
            "status": "approved" if decision.approved else "rejected",
            "decided_by": actor,
            "decided_at": datetime.now(UTC).isoformat(),
        }
        if decision.approved:
            # The receipt IS the dummy write. Commit it atomically with the decision, not an external side effect.
            changed["dummy_receipt"] = {
                "tool": TOOL_NAME,
                "arguments": record["arguments"],
                "args_hash": record["args_hash"],
            }
        await self.replace(store, record["pending_id"], changed, item.etag)
        return [Content.from_text(json.dumps(changed, sort_keys=True))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--state-dir", type=Path, required=True, help="Local SDK storage directory; keep outside git.")
    args = parser.parse_args()
    if os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT"):
        parser.error(
            "This entry point is local-only; hosted publishing requires a reviewed platform-user configuration."
        )
    os.environ["AGENTSERVER_STATE_ROOT"] = str(args.state_dir.resolve())
    logging.basicConfig(level=logging.INFO)
    ResponsesHostServer(ApprovalSpikeAgent(allow_local=True), history_source="agent").run(
        host="127.0.0.1", port=args.port
    )


if __name__ == "__main__":
    main()
