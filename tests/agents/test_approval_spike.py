import asyncio
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from agent_framework import Content, Message
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.core.storage import FoundryStateStore
from documentation_agent.approval_spike import (
    STORE_NAME,
    TOOL_NAME,
    ApprovalSpikeAgent,
    DummyArguments,
    arguments_hash,
)
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT", raising=False)


@pytest.fixture
def proposal():
    return {
        "action": "propose",
        "arguments": {"run_id": str(uuid4()), "page": "/approval-spike", "content": "Fictional proposed text."},
        "evidence": [
            {
                "id": "demo",
                "source": "git",
                "uri": "https://example.com/fictional/source",
                "version": "a" * 40,
                "excerpt": "Fictional source excerpt for the approval demo.",
            }
        ],
    }


async def propose(agent, session, proposal):
    response = await agent.run(json.dumps(proposal), session=session)
    return next(content for content in response.messages[0].contents if content.type == "function_approval_request")


async def inspect_record(agent, session, pending_id):
    response = await agent.run(json.dumps({"action": "inspect", "pending_id": pending_id}), session=session)
    return json.loads(response.text)


def test_native_approval_waits_then_commits_once(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        before = await inspect_record(agent, session, approval.id)
        assert before["status"] == "pending"
        assert "dummy_receipt" not in before
        decision = Message("user", [approval.to_function_approval_response(True)])
        response = await agent.run(decision, session=session)
        after = json.loads(response.text)
        assert after["dummy_receipt"]["arguments"] == proposal["arguments"]
        assert after["dummy_receipt"]["tool"] == TOOL_NAME
        assert after["status"] == "approved"
        assert after["decided_by"] == "local-unverified"
        with pytest.raises(ValueError, match="duplicate or stale"):
            await agent.run(decision, session=session)
        assert await inspect_record(agent, session, approval.id) == after

    asyncio.run(run())


def test_reject_never_creates_receipt_or_allows_later_approve(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        await agent.run(Message("user", [approval.to_function_approval_response(False)]), session=session)
        record = await inspect_record(agent, session, approval.id)
        assert record["status"] == "rejected"
        assert "dummy_receipt" not in record
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(Message("user", [approval.to_function_approval_response(True)]), session=session)

    asyncio.run(run())


def test_modify_voids_original_and_requires_fresh_native_approval(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        original = await propose(agent, session, proposal)
        response = await agent.run(
            json.dumps(
                {
                    "action": "modify",
                    "pending_id": original.id,
                    "feedback": "Use the revised wording.",
                    "content": "Revised fictional text.",
                }
            ),
            session=session,
        )
        new = next(content for content in response.messages[0].contents if content.type == "function_approval_request")
        assert new.id != original.id
        old_record = await inspect_record(agent, session, original.id)
        assert old_record["status"] == "modified"
        assert old_record["feedback"] == "Use the revised wording."
        assert "dummy_receipt" not in old_record
        new_record = await inspect_record(agent, session, new.id)
        assert new_record["status"] == "pending"
        assert new_record["args_hash"] != old_record["args_hash"]
        with pytest.raises(ValueError):
            await agent.run(Message("user", [original.to_function_approval_response(True)]), session=session)
        await agent.run(Message("user", [new.to_function_approval_response(True)]), session=session)
        receipt = (await inspect_record(agent, session, new.id))["dummy_receipt"]
        assert receipt["arguments"]["content"] == "Revised fictional text."
        assert receipt["arguments"]["run_id"] == proposal["arguments"]["run_id"]

    asyncio.run(run())


@pytest.mark.parametrize("change", ["content", "run_id", "tool", "call_id", "hash"])
def test_tampering_rejected_without_receipt(proposal, change):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        decision = Content.from_dict(approval.to_function_approval_response(True).to_dict())
        if change == "content":
            decision.function_call.arguments = {**proposal["arguments"], "content": "Changed outside approval"}
        elif change == "run_id":
            decision.function_call.arguments = {**proposal["arguments"], "run_id": str(uuid4())}
        elif change == "tool":
            decision.function_call.name = "wiki_upsert_page"
        elif change == "call_id":
            decision.function_call.call_id = "different-call"
        else:
            store = await FoundryStateStore.get_or_create(STORE_NAME, user_isolation=True)
            async with store:
                record = await store.get_item(approval.id)
                await store.set_item(approval.id, {**record.value, "args_hash": "invalid"}, if_match=record.etag)
        with pytest.raises(ValueError):
            await agent.run(Message("user", [decision]), session=session)
        assert "dummy_receipt" not in await inspect_record(agent, session, approval.id)

    asyncio.run(run())


def test_restart_retains_pending_and_decided_state(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        saved_session = session.to_dict()
        from agent_framework import AgentSession

        restarted = ApprovalSpikeAgent(allow_local=True)
        restored = AgentSession.from_dict(saved_session)
        await restarted.run(Message("user", [approval.to_function_approval_response(True)]), session=restored)
        with pytest.raises(ValueError):
            await ApprovalSpikeAgent(allow_local=True).run(
                Message("user", [approval.to_function_approval_response(True)]),
                session=AgentSession.from_dict(saved_session),
            )

    asyncio.run(run())


def test_cross_session_approval_rejected(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        approval = await propose(agent, agent.create_session(), proposal)
        with pytest.raises(ValueError, match="reviewer or session"):
            await agent.run(
                Message("user", [approval.to_function_approval_response(True)]), session=agent.create_session()
            )

    asyncio.run(run())


def test_different_reviewer_cannot_decide(proposal, monkeypatch):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        monkeypatch.setattr(agent, "actor", lambda: "reviewer-a")
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        monkeypatch.setattr(agent, "actor", lambda: "reviewer-b")
        with pytest.raises(ValueError, match="reviewer or session"):
            await agent.run(Message("user", [approval.to_function_approval_response(True)]), session=session)

    asyncio.run(run())


def test_stale_etag_cannot_overwrite_committed_decision(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        store = await FoundryStateStore.get_or_create(STORE_NAME, user_isolation=True)
        async with store:
            stale = await store.get_item(approval.id)
            await agent.run(Message("user", [approval.to_function_approval_response(False)]), session=session)
            with pytest.raises(ValueError, match="replay rejected"):
                await agent.replace(store, approval.id, {**stale.value, "status": "approved"}, stale.etag)
        assert (await inspect_record(agent, session, approval.id))["status"] == "rejected"

    asyncio.run(run())


def test_unverified_hosted_actor_is_rejected(proposal):
    agent = ApprovalSpikeAgent()
    with pytest.raises(ValueError, match="Verified platform user"):
        asyncio.run(agent.run(json.dumps(proposal), session=agent.create_session()))


def test_atomic_competing_decisions_commit_at_most_one(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        approval = await propose(agent, session, proposal)
        decision = Message("user", [approval.to_function_approval_response(True)])
        outcomes = await asyncio.gather(
            agent.run(decision, session=session), agent.run(decision, session=session), return_exceptions=True
        )
        assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
        assert (await inspect_record(agent, session, approval.id))["status"] == "approved"

    asyncio.run(run())


def test_argument_hash_is_canonical_and_covers_run_id(proposal):
    args = DummyArguments.model_validate(proposal["arguments"])
    reordered = DummyArguments.model_validate(dict(reversed(list(proposal["arguments"].items()))))
    assert arguments_hash(args) == arguments_hash(reordered)
    other = args.model_copy(update={"run_id": uuid4()})
    assert arguments_hash(args) != arguments_hash(other)


def test_preview_contains_inline_evidence_and_exact_arguments(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        response = await agent.run(json.dumps(proposal), session=agent.create_session())
        for value in (proposal["evidence"][0]["uri"], "a" * 40, proposal["arguments"]["content"], "Arguments SHA-256"):
            assert value in response.text
        assert "not a wiki write" in response.text

    asyncio.run(run())


def test_no_text_approve_command_or_arbitrary_write_target(proposal):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        bad = deepcopy(proposal)
        bad["arguments"]["page"] = "/real-wiki"
        for message in [json.dumps(bad), "approve", '{"action":"approve"}']:
            with pytest.raises(ValueError):
                await agent.run(message, session=session)

    asyncio.run(run())


def test_local_header_identity_is_not_treated_as_verified(monkeypatch):
    from azure.ai.agentserver.core import FoundryAgentRequestContext

    monkeypatch.setattr(
        "documentation_agent.approval_spike.get_request_context",
        lambda: FoundryAgentRequestContext(user_id="caller-claimed-identity"),
    )
    assert ApprovalSpikeAgent(allow_local=True).actor() == "local-unverified"
    with pytest.raises(ValueError):
        ApprovalSpikeAgent().actor()


def test_modified_call_stays_invalid_if_replacement_storage_fails(proposal, monkeypatch):
    async def run():
        agent = ApprovalSpikeAgent(allow_local=True)
        session = agent.create_session()
        approval = await propose(agent, session, proposal)

        async def failed_create(*args, **kwargs):
            raise ConnectionError("storage unavailable")

        monkeypatch.setattr(FoundryStateStore, "create_item", failed_create)
        with pytest.raises(ConnectionError):
            await agent.run(
                json.dumps(
                    {
                        "action": "modify",
                        "pending_id": approval.id,
                        "feedback": "Revise it",
                        "content": "New text",
                    }
                ),
                session=session,
            )
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.run(Message("user", [approval.to_function_approval_response(True)]), session=session)
        assert "dummy_receipt" not in await inspect_record(agent, session, approval.id)

    asyncio.run(run())


def test_native_http_approval_and_old_response_replay(proposal):
    async def run():
        server = ResponsesHostServer(ApprovalSpikeAgent(allow_local=True), history_source="agent")
        async with AsyncClient(transport=ASGITransport(app=server), base_url="http://localhost") as client:
            response = await client.post("/responses", json={"input": json.dumps(proposal), "stream": False})
            response.raise_for_status()
            first = response.json()
            assert first["status"] == "completed", first
            pending = next(item for item in first["output"] if item["type"] == "mcp_approval_request")
            assert json.loads(pending["arguments"]) == proposal["arguments"]
            decision = {
                "input": [{"type": "mcp_approval_response", "approval_request_id": pending["id"], "approve": True}],
                "previous_response_id": first["id"],
                "stream": False,
            }
            approved = (await client.post("/responses", json=decision)).json()
            assert approved["status"] == "completed", approved
            record = json.loads(
                next(
                    part["text"] for item in approved["output"] if item["type"] == "message" for part in item["content"]
                )
            )
            assert record["status"] == "approved"
            # Forking from the original pending response must not replay the write.
            replay = (await client.post("/responses", json=decision)).json()
            assert replay["status"] == "failed", replay
            assert "no longer pending" in replay["error"]["message"]

    asyncio.run(run())


def test_native_http_modify_and_reject(proposal):
    async def run():
        server = ResponsesHostServer(ApprovalSpikeAgent(allow_local=True), history_source="agent")
        async with AsyncClient(transport=ASGITransport(app=server), base_url="http://localhost") as client:
            first = (await client.post("/responses", json={"input": json.dumps(proposal), "stream": False})).json()
            pending = next(item for item in first["output"] if item["type"] == "mcp_approval_request")
            preview = next(
                part["text"] for item in first["output"] if item["type"] == "message" for part in item["content"]
            )
            pending_id = next(
                line.removeprefix("Pending ID: ") for line in preview.splitlines() if line.startswith("Pending ID: ")
            )
            modified = (
                await client.post(
                    "/responses",
                    json={
                        "previous_response_id": first["id"],
                        "stream": False,
                        "input": json.dumps(
                            {
                                "action": "modify",
                                "pending_id": pending_id,
                                "feedback": "Revise the sample.",
                                "content": "New fictional text",
                            }
                        ),
                    },
                )
            ).json()
            assert modified["status"] == "completed", modified
            new = next(item for item in modified["output"] if item["type"] == "mcp_approval_request")
            assert new["id"] != pending["id"]
            assert json.loads(new["arguments"])["content"] == "New fictional text"
            old = (
                await client.post(
                    "/responses",
                    json={
                        "previous_response_id": first["id"],
                        "stream": False,
                        "input": [
                            {"type": "mcp_approval_response", "approval_request_id": pending["id"], "approve": True}
                        ],
                    },
                )
            ).json()
            assert old["status"] == "failed", old
            rejected = (
                await client.post(
                    "/responses",
                    json={
                        "previous_response_id": modified["id"],
                        "stream": False,
                        "input": [
                            {"type": "mcp_approval_response", "approval_request_id": new["id"], "approve": False}
                        ],
                    },
                )
            ).json()
            assert rejected["status"] == "completed", rejected
            text = next(
                part["text"] for item in rejected["output"] if item["type"] == "message" for part in item["content"]
            )
            assert json.loads(text)["status"] == "rejected"
            assert "dummy_receipt" not in json.loads(text)

    asyncio.run(run())
