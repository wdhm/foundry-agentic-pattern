import asyncio
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from documentation_agent.approval import ToolApprovalAgent, ToolApprovalPolicy
from documentation_agent.wiki_drafts import WikiDraftPublisher
from mcp.types import Tool

from contracts.wiki import WikiSnapshot


def snapshot(path, content):
    raw = content.encode()
    etag = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return WikiSnapshot(path=path, content=content, etag=etag, uri="https://dev.azure.com/test/wiki")


def harness():
    policy = ToolApprovalPolicy(
        toolbox_endpoint="https://test.services.ai.azure.com/api/projects/test/toolboxes/write/versions/1/mcp?api-version=v1",
        tool_name="ado___wiki_upsert_page",
        fixed_arguments={
            "project": "test", "wikiIdentifier": "wiki", "branch": "wikiMaster", "path": "/Order Sync/Overview",
        },
        content_parameter="content", wiki_etag_parameter="etag", review_draft_prefix="/Drafts/Order Sync",
    )
    pages = {"/Drafts/Order Sync": snapshot("/Drafts/Order Sync", "# Drafts")}
    writes = []

    async def write(arguments):
        writes.append(dict(arguments))
        pages[arguments["path"]] = snapshot(arguments["path"], arguments["content"])
        return {"created": True}

    call = AsyncMock(side_effect=write)
    spec = Tool(name=policy.tool_name, inputSchema={
        "type": "object",
        "properties": {k: {"type": "string"} for k in ("project", "wikiIdentifier", "branch", "path", "content")},
        "required": ["project", "wikiIdentifier", "path", "content"],
    })

    @asynccontextmanager
    async def connector(target):
        assert target.fixed_arguments["path"].startswith("/Drafts/Order Sync/PR-")
        assert target.wiki_etag_parameter is None and target.review_draft_prefix is None
        yield SimpleNamespace(spec=spec, invoke_once=call)

    reader = AsyncMock(side_effect=lambda path: pages[path])
    return WikiDraftPublisher(policy, reader, connector=connector), pages, writes, reader, call


def test_publisher_creates_only_generated_draft_pages_and_checks_readback():
    async def run():
        publisher, pages, writes, _, call = harness()
        event = uuid4()
        bundle = await publisher.publish(event, 12, "# Proposed actual page", "# Diff and evidence")
        assert bundle.page.path == f"/Drafts/Order Sync/PR-12/Review-{event}/Draft"
        assert bundle.notes.path == bundle.page.path.removesuffix("/Draft") + "/Changes"
        assert bundle.page.content == "# Proposed actual page"
        assert bundle.notes.content == "# Diff and evidence"
        assert len(writes) == 5 and call.await_count == 5
        assert "/Order Sync/Overview" not in pages
        revision = uuid4()
        revised = await publisher.publish(event, 12, "Revised", "New notes", revision_id=revision)
        assert revised.page.path == f"/Drafts/Order Sync/PR-12/Review-{event}/Revisions/Revision-{revision}/Draft"
        assert len(writes) == 8
        assert pages[bundle.page.path].content == "# Proposed actual page"
        agent = ToolApprovalAgent(publisher.policy, wiki_reader=publisher.reader)
        agent.check_draft(bundle.page, bundle.page.content, bundle.notes)
        agent.check_draft(revised.page, revised.page.content, revised.notes)
        with pytest.raises(ValueError, match="same draft"):
            agent.check_draft(revised.page, revised.page.content, bundle.notes)

    asyncio.run(run())


def test_publisher_requires_parent_and_never_creates_arbitrary_targets():
    async def run():
        publisher, pages, writes, _, _ = harness()
        pages.clear()
        with pytest.raises(KeyError):
            await publisher.publish(uuid4(), 12, "Content", None)
        assert writes == []
        for path in ("/Order Sync/Overview", "/Drafts/Order Sync/PR-1-../../live", "/Drafts/Other"):
            with pytest.raises(ValueError):
                await publisher.write_once(path, "Content")
        assert writes == []

    asyncio.run(run())


def test_publisher_does_not_report_success_on_readback_mismatch():
    async def run():
        publisher, _, _, reader, call = harness()
        event = uuid4()
        reader.side_effect = [
            snapshot("/Drafts/Order Sync", "# Drafts"),
            snapshot("/Drafts/Order Sync/PR-12", "Different content"),
        ]
        with pytest.raises(ValueError, match="readback differs"):
            await publisher.publish(event, 12, "Expected content", None)
        call.assert_awaited_once()

    asyncio.run(run())
