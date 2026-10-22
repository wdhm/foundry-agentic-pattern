import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agent_framework import Message
from azure.ai.agentserver.core.storage import FoundryStateStore
from documentation_agent.approval import STORE_NAME, PendingCall, ToolApprovalAgent, ToolApprovalPolicy
from documentation_agent.wiki_page import compose_page, review_notes, snapshot_from_output
from mcp.types import Tool

from contracts.v1 import AgentResult
from contracts.wiki import WikiSnapshot

PATH = "/Order Sync/Overview"


def snapshot(content, path=PATH):
    raw = content.encode("utf-8")
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return WikiSnapshot(path=path, content=content, etag=f'"{blob}"', uri="https://dev.azure.com/test/wiki/Overview")


def assessment(changes):
    return AgentResult.model_validate({
        "contract_version": "1.0.0", "request_id": str(uuid4()),
        "documentation_status": "gaps_found", "requires_human_review": True, "confidence": 0.8,
        "findings": [{
            "category": "retry", "severity": "medium",
            "description": "Document retry behavior", "evidence_refs": ["code"],
        }],
        "proposed_changes": [
            {"target_page": PATH, "target_section": title, "proposed_content": content, "evidence_refs": ["code"]}
            for title, content in changes
        ],
        "missing_information": [],
        "evidence": [{
            "id": "code", "source": "git", "uri": "https://example.com/source",
            "version": "a" * 40, "excerpt": "maxAttempts=5",
        }],
        "provenance": {
            "agent_name": "documentation-agent", "agent_version": "0.4.0", "contract_version": "1.0.0",
            "model": "test", "model_version": "test", "prompt_version": "test", "policy_version": "test",
        },
    })


def test_full_page_replaces_selected_body_preserves_title_intro_and_unrelated_sections():
    base = snapshot(
        "# Order Sync overview\n\nIntroduction and source link.\n\n"
        "## Retries\n\nRetry three times.\n\n### Notes\nOld retry note.\n\n"
        "## Ownership\n\nKeep this manual information exactly.\n"
    )
    result = assessment([("Retries", "Retry five times with exponential backoff."), ("Timeout", "ERP timeout is 30s.")])
    updated = compose_page(base, result)
    assert updated.startswith("# Order Sync overview\n\nIntroduction and source link.\n\n")
    assert "## Ownership\n\nKeep this manual information exactly.\n" in updated
    assert "Retry three times." not in updated
    assert "Old retry note." not in updated
    assert "## Retries\n\nRetry five times with exponential backoff.\n\n## Ownership" in updated
    assert updated.endswith("## Timeout\n\nERP timeout is 30s.\n")
    assert "# Documentation assessment review" not in updated
    assert "## Findings" not in updated


def test_current_short_overview_becomes_actual_documentation_not_a_report():
    original = "# Order Sync overview\n\nOriginal overview.\n\n**Source:** Work item #1."
    base = snapshot(original)
    updated = compose_page(base, assessment([("Retry policy", "Retry five times. See the pinned configuration.")]))
    assert updated == original + "\n\n## Retry policy\n\nRetry five times. See the pinned configuration.\n"


def test_code_fence_heading_is_not_a_section_boundary():
    original = "# Title\n\n## Untouched\n\n```md\n## Retries\nexample\n```\n\n## Retries\n\nOld\n"
    updated = compose_page(snapshot(original), assessment([("Retries", "New")]))
    assert "## Untouched\n\n```md\n## Retries\nexample\n```\n\n" in updated
    assert updated.endswith("## Retries\n\nNew\n\n")


def test_crlf_and_matching_section_heading_preserved():
    base = snapshot("# Title\r\n\r\n## Retries\r\n\r\nOld\r\n\r\n## Other\r\nKeep\r\n")
    updated = compose_page(base, assessment([(" retries ", "## Retries\n\nNew\n### Detail\nText")]))
    assert "## Retries\r\n\r\nNew\r\n### Detail\r\nText\r\n\r\n## Other\r\nKeep\r\n" in updated
    assert "\n" not in updated.replace("\r\n", "")


@pytest.mark.parametrize(
    "source,changes",
    [
        ("# Title\n\n## Retries\nA\n## retries\nB\n", [("Retries", "New")]),
        ("# Title\n\n```\n## Retries\n", [("Retries", "New")]),
        ("# Title\n\n<div>\n## Retries\n</div>", [("Retries", "New")]),
        ("# Title\n\nRetries\n-------\nOld", [("Retries", "New")]),
        ("# Title\n\nText", [("Retries", "# New page title\nDiscard original")]),
        ("# Title\n\nText", [("Retries", "## Other\nDifferent")]),
        ("# Title\n\nText", [("Retries", "Unsectioned content\n## Retries\nNew\n## Other\nInjected")]),
        ("# Title\n\nText", [("Retries", "One"), ("retries", "Two")]),
        ("# Title\n\nText", [("Retries\n## Other", "New")]),
        ("# Title\n\nText", [("Retries", "x" * 16001)]),
    ],
)
def test_ambiguous_or_unsafe_composition_fails_without_guessing(source, changes):
    with pytest.raises(ValueError):
        compose_page(snapshot(source), assessment(changes))


def test_notes_contain_diff_evidence_and_base_version_but_are_separate_from_page():
    base = snapshot("# Title\n\n## Retries\n\nOld\n")
    result = assessment([("Retries", "New")])
    updated = compose_page(base, result)
    notes = review_notes(base, updated, result)
    assert "-Old" in notes and "+New" in notes
    assert base.etag in notes and result.evidence[0].uri in notes
    assert "## Evidence" not in updated
    assert "## Evidence" in notes


def test_grouped_proposals_use_explicit_h2_sections_preserving_unrelated_content():
    base = snapshot("# Title\n\nManual introduction.\n\n## Owner\n\nKeep owner.\n\n## Retry\n\nOld retry.\n")
    result = assessment([(
        "Add retry and timeout sections",
        "## Retry\n\nNew retry.\n\n## Timeout\n\nNew timeout.\n",
    )])
    updated = compose_page(base, result)
    assert updated.startswith("# Title\n\nManual introduction.\n\n## Owner\n\nKeep owner.\n\n")
    assert "## Retry\n\nNew retry." in updated
    assert "## Timeout\n\nNew timeout." in updated
    assert "Old retry." not in updated


@pytest.mark.parametrize("shape", ["string", "list"])
def test_tool_snapshot_validates_exact_page_and_git_blob(shape):
    expected = snapshot("# Title\n\nCurrent content")
    payload = {
        "page": {"path": PATH, "content": expected.content, "remoteUrl": expected.uri},
        "eTag": expected.etag if shape == "string" else [expected.etag],
    }
    assert snapshot_from_output(json.dumps(payload), PATH) == expected
    for altered in (
        {**payload, "eTag": ['"latest"']},
        {**payload, "eTag": ['"' + "f" * 40 + '"']},
        {**payload, "page": {**payload["page"], "path": "/Other"}},
        {**payload, "page": {**payload["page"], "content": "different"}},
        {**payload, "eTag": [expected.etag, expected.etag]},
    ):
        with pytest.raises(ValueError):
            snapshot_from_output(json.dumps(altered), PATH)


@pytest.fixture
def conditional(tmp_path, monkeypatch):
    monkeypatch.delenv("FOUNDRY_HOSTING_ENVIRONMENT", raising=False)
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path / "state"))
    current = [snapshot("# Order Sync overview\n\nExisting information.\n")]
    policy = ToolApprovalPolicy(
        toolbox_endpoint="https://test.services.ai.azure.com/api/projects/test/toolboxes/write/versions/1/mcp?api-version=v1",
        tool_name="ado___wiki_upsert_page", content_parameter="content", wiki_etag_parameter="etag",
        fixed_arguments={"project": "test", "wikiIdentifier": "wiki", "path": PATH, "branch": "wikiMaster"},
    )
    spec = Tool(name=policy.tool_name, inputSchema={
        "type": "object",
        "properties": {
            name: {"type": "string"} for name in ("project", "wikiIdentifier", "path", "branch", "content", "etag")
        },
        "required": ["project", "wikiIdentifier", "path", "content"],
    })
    connection = type("Connection", (), {})()
    connection.spec = spec

    async def write(args):
        if args["etag"] != current[0].etag:
            raise RuntimeError("412 Precondition failed")
        current[0] = snapshot(args["content"])
        return {"updated": True}

    connection.invoke_once = AsyncMock(side_effect=write)

    @asynccontextmanager
    async def connector(_):
        yield connection

    reader = AsyncMock(side_effect=lambda path: current[0])
    agent = ToolApprovalAgent(policy, connector=connector, allow_local=True, wiki_reader=reader)
    command = {
        "action": "propose", "run_id": str(uuid4()), "content": "# Order Sync overview\n\nUpdated documentation.\n",
        "expected_wiki_etag": current[0].etag,
        "evidence": assessment([]).model_dump(mode="json")["evidence"],
    }
    return agent, command, current, connection, reader


async def propose(agent, session, command):
    output = await agent.execute(json.dumps(command), session)
    return next(item for item in output if item.type == "function_approval_request")


def test_approved_etag_is_forwarded_and_exact_page_readback_is_recorded(conditional):
    async def run():
        agent, command, current, connection, reader = conditional
        session = agent.create_session()
        approval = await propose(agent, session, command)
        assert approval.function_call.arguments["etag"] == command["expected_wiki_etag"]
        output = await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        record = PendingCall.model_validate_json(output[0].text)
        assert record.status == "succeeded"
        assert record.result["wiki_readback"]["etag"] == current[0].etag
        assert current[0].content == command["content"]
        assert reader.await_count == 2
        connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_stale_base_stops_before_write_and_cannot_be_tampered_to_latest(conditional):
    async def run():
        agent, command, current, connection, _ = conditional
        session = agent.create_session()
        approval = await propose(agent, session, command)
        current[0] = snapshot("# Another person's edit\n")
        with pytest.raises(ValueError, match="Wiki changed"):
            await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        decision = approval.to_function_approval_response(True)
        decision.function_call.arguments = {**decision.function_call.arguments, "etag": current[0].etag}
        with pytest.raises(ValueError, match="arguments were changed"):
            await agent.execute(Message("user", [decision]), session)
        connection.invoke_once.assert_not_called()
        assert current[0].content == "# Another person's edit\n"

    asyncio.run(run())


def test_modify_retains_base_version_and_requires_new_approval(conditional):
    async def run():
        agent, command, current, connection, _ = conditional
        session = agent.create_session()
        approval = await propose(agent, session, command)
        changed = await agent.execute(json.dumps({
            "action": "modify", "pending_id": approval.id, "content": "Revised complete page", "feedback": "Clarify",
        }), session)
        replacement = next(item for item in changed if item.type == "function_approval_request")
        assert replacement.function_call.arguments["etag"] == command["expected_wiki_etag"]
        current[0] = snapshot("Concurrent edit")
        with pytest.raises(ValueError, match="Wiki changed"):
            await agent.execute(Message("user", [replacement.to_function_approval_response(True)]), session)
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("missing", [None, "*", "", "latest"])
def test_real_page_proposal_requires_concrete_etag(conditional, missing):
    async def run():
        agent, command, _, connection, _ = conditional
        command["expected_wiki_etag"] = missing
        with pytest.raises(ValueError):
            await propose(agent, agent.create_session(), command)
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_readback_mismatch_is_unknown_and_not_retried(conditional):
    async def run():
        agent, command, _, connection, _ = conditional
        # Tool reports success but did not write: never return a successful approval.
        connection.invoke_once.side_effect = None
        connection.invoke_once.return_value = {"updated": True}
        session = agent.create_session()
        approval = await propose(agent, session, command)
        with pytest.raises(ValueError, match="readback differs"):
            await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        store = await FoundryStateStore.get_or_create(STORE_NAME, user_isolation=True)
        async with store:
            assert (await store.get_item(approval.id)).value["status"] == "outcome_unknown"
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_write_race_passes_original_etag_and_does_not_retry(conditional):
    async def run():
        agent, command, current, connection, _ = conditional

        async def race(args):
            assert args["etag"] == command["expected_wiki_etag"]
            current[0] = snapshot("Other editor wins after precheck")
            raise RuntimeError("412 Precondition failed")

        connection.invoke_once.side_effect = race
        session = agent.create_session()
        approval = await propose(agent, session, command)
        with pytest.raises(RuntimeError, match="412"):
            await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        assert current[0].content == "Other editor wins after precheck"
        with pytest.raises(ValueError, match="no longer pending"):
            await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        connection.invoke_once.assert_awaited_once()

    asyncio.run(run())


def test_deleted_page_read_error_never_dispatches(conditional):
    async def run():
        agent, command, _, connection, reader = conditional
        session = agent.create_session()
        approval = await propose(agent, session, command)
        reader.side_effect = ValueError("Page not found")
        with pytest.raises(ValueError, match="not found"):
            await agent.execute(Message("user", [approval.to_function_approval_response(True)]), session)
        connection.invoke_once.assert_not_called()

    asyncio.run(run())


def test_real_policy_cannot_start_without_a_snapshot_reader(conditional):
    from documentation_agent.approval import wiki_reader_from_environment

    agent = conditional[0]
    with pytest.raises(ValueError, match="readback adapter"):
        ToolApprovalAgent(agent.policy)
    assert wiki_reader_from_environment(agent.policy.model_copy(update={"wiki_etag_parameter": None})) is None
