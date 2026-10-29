"""Automatic writes limited to fresh review pages, never the published page."""

import asyncio
from uuid import UUID

from contracts.wiki import WikiDraftBundle, WikiSnapshot

from .approval import Connector, ToolApprovalPolicy, WikiRead, connect_tool, validate_schema
from .draft_layout import review_path, writable_path


class WikiDraftPublisher:
    def __init__(
        self, policy: ToolApprovalPolicy, reader: WikiRead, *,
        root: str = "/Drafts/Order Sync", connector: Connector = connect_tool,
    ) -> None:
        if root != "/Drafts/Order Sync":
            raise ValueError("Automatic draft publication is restricted to /Drafts/Order Sync.")
        if policy.tool_name != "ado___wiki_upsert_page" or policy.content_parameter != "content":
            raise ValueError("Draft publication requires the reviewed wiki upsert tool.")
        self.policy = policy
        self.reader = reader
        self.root = root
        self.connector = connector

    async def publish(
        self, event_id: UUID, pr_id: int, content: str, notes: str | None, *, revision_id: UUID | None = None,
    ) -> WikiDraftBundle:
        if pr_id <= 0 or not content.strip() or len(content) > 16000:
            raise ValueError("Invalid draft PR or page content.")
        if notes is not None and (not notes.strip() or len(notes) > 64000):
            raise ValueError("Invalid review notes.")
        review = review_path(event_id, pr_id)
        container = f"{review}/Revisions/Revision-{revision_id}" if revision_id else review
        async with asyncio.timeout(self.policy.timeout_seconds):
            # The parent must already exist. Never mistake permission/network
            # failures for permission to create arbitrary parent pages.
            parent = await self.reader(self.root)
            if parent.path != self.root:
                raise ValueError("Draft root readback does not match.")
            if revision_id is None:
                await self.write_once(
                    f"{self.root}/PR-{pr_id}",
                    f"# PR {pr_id} documentation reviews\n\nGenerated review area. Not published documentation.\n",
                )
                await self.write_once(review, "# Documentation review\n\nRead **Draft** and **Changes** below.\n")
                await self.write_once(review + "/Revisions", "# Revisions\n\nEach revision requires a new approval.\n")
            else:
                existing = await self.reader(review + "/Revisions")
                if existing.path != review + "/Revisions":
                    raise ValueError("Revision parent belongs to another review.")
                await self.write_once(container, "# Revised proposal\n\nRead **Draft** and **Changes** below.\n")
            page = await self.write_once(container + "/Draft", content)
            changes = await self.write_once(container + "/Changes", notes) if notes is not None else None
        return WikiDraftBundle(page=page, notes=changes)

    async def write_once(self, path: str, content: str) -> WikiSnapshot:
        if not writable_path(path):
            raise ValueError("Automatic writes cannot target published documentation.")
        values = self.policy.model_dump()
        values.update(
            fixed_arguments={**self.policy.fixed_arguments, "path": path},
            wiki_etag_parameter=None, review_draft_prefix=None,
        )
        draft_policy = ToolApprovalPolicy.model_validate(values)
        async with self.connector(draft_policy) as connection:
            if connection.spec.name != draft_policy.tool_name:
                raise ValueError("Unexpected draft tool.")
            arguments = draft_policy.arguments(content)
            validate_schema(connection.spec.inputSchema, arguments)
            # Event/revision UUID makes each path fresh; the outer event claim
            # prevents retries. An uncertain call requires operator reconciliation.
            await connection.invoke_once(arguments)
        actual = await self.reader(path)
        if actual.path != path or actual.content != content:
            raise ValueError("Draft page readback differs from the prepared content.")
        return actual
