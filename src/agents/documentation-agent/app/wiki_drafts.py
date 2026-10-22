"""Automatic writes limited to fresh review pages, never the published page."""

import asyncio
import re
from uuid import UUID

from contracts.wiki import WikiDraftBundle, WikiSnapshot

from .approval import Connector, ToolApprovalPolicy, WikiRead, connect_tool, validate_schema


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
        suffix = f"-revision-{revision_id}" if revision_id else ""
        path = f"{self.root}/PR-{pr_id}-{event_id}{suffix}"
        async with asyncio.timeout(self.policy.timeout_seconds):
            # The parent must already exist. Never mistake permission/network
            # failures for permission to create arbitrary parent pages.
            parent = await self.reader(self.root)
            if parent.path != self.root:
                raise ValueError("Draft root readback does not match.")
            page = await self.write_once(path, content)
            review = await self.write_once(path + "-review", notes) if notes is not None else None
        return WikiDraftBundle(page=page, notes=review)

    async def write_once(self, path: str, content: str) -> WikiSnapshot:
        tail = path.removeprefix(self.root + "/")
        if (
            not path.startswith(self.root + "/PR-")
            or re.fullmatch(r"PR-[1-9]\d*-[0-9a-f-]{36}(?:-revision-[0-9a-f-]{36})?(?:-review)?", tail) is None
        ):
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
