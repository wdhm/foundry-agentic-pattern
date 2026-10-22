"""Read and compose a complete wiki page without rewriting unrelated Markdown."""

import asyncio
import difflib
import json
import re
from dataclasses import dataclass

from agent_framework_foundry_hosting import FoundryToolbox
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

from contracts.v1 import AgentResult
from contracts.wiki import WikiSnapshot

from .read_policy import parse_read_result
from .settings import AssessmentSettings


class ToolboxWikiReader:
    def __init__(self, settings: AssessmentSettings) -> None:
        self.settings = settings

    async def __call__(self, path: str) -> WikiSnapshot:
        credential = AzureCliCredential() if self.settings.auth_mode == "azure_cli" else ManagedIdentityCredential()
        async with (
            asyncio.timeout(self.settings.timeout_seconds),
            credential,
            FoundryToolbox(
                credential, url=self.settings.toolbox_endpoint, allowed_tools=["ado___wiki"],
                tool_name_prefix="", approval_mode="never_require", parse_tool_results=parse_read_result,
            ) as toolbox,
        ):
            if {tool.name for tool in toolbox.functions} != {"ado___wiki"}:
                raise ValueError("Read Toolbox is missing the wiki page tool.")
            output = await toolbox.call_tool(
                "ado___wiki", action="get_page", project=self.settings.ado_project,
                wikiIdentifier=self.settings.ado_wiki, path=path, includeContent=True,
            )
            if not isinstance(output, str):
                raise ValueError("Unexpected wiki read result.")
            return snapshot_from_output(output, path)


def snapshot_from_output(output: str, path: str) -> WikiSnapshot:
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise ValueError("Wiki read did not return a page and ETag.")
    page = payload.get("page")
    etags = payload.get("eTag")
    if isinstance(etags, str):
        etags = [etags]
    if not isinstance(page, dict) or page.get("path") != path or not isinstance(etags, list) or len(etags) != 1:
        raise ValueError("Wiki read must identify exactly the requested existing page and one ETag.")
    return WikiSnapshot.model_validate({
        "path": path, "content": page.get("content"), "etag": etags[0],
        "uri": page.get("remoteUrl") or page.get("url"),
    })


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    start: int
    body_start: int


def headings(markdown: str) -> list[Heading]:
    """Constrained ATX composer: reject unsupported/ambiguous markup, never guess."""
    result: list[Heading] = []
    fence_char, fence_length = "", 0
    previous_nonblank = False
    offset = 0
    for line in markdown.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", stripped)
        if fence_char:
            if fence and fence[1][0] == fence_char and len(fence[1]) >= fence_length and not fence[2].strip():
                fence_char = ""
        elif fence:
            fence_char, fence_length = fence[1][0], len(fence[1])
        else:
            # Reject HTML blocks/comments and Setext headers rather than risk
            # treating a heading-looking line inside them as an editable section.
            if re.match(r"^ {0,3}<", stripped):
                raise ValueError("Page composition does not support raw HTML blocks; review this page manually.")
            if previous_nonblank and re.fullmatch(r" {0,3}(?:=+|-+)\s*", stripped):
                raise ValueError("Use ATX (#/##) headings; Setext headings are ambiguous for this composer.")
            heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", stripped)
            if heading:
                title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2]).strip()
                result.append(Heading(len(heading[1]), title, offset, offset + len(line)))
        previous_nonblank = bool(stripped.strip())
        offset += len(line)
    if fence_char:
        raise ValueError("Unclosed code fence; refusing to compose a page inside it.")
    return result


def section_key(title: str) -> str:
    if (
        not title.strip() or len(title) > 160
        or any(ord(c) < 32 for c in title) or any(c in title for c in "#<>[]")
    ):
        raise ValueError("Proposed section must be a plain, nonblank heading name.")
    return " ".join(title.split()).casefold()


def section_body(content: str, target: str) -> str:
    parsed = headings(content)
    if any(h.level == 1 for h in parsed):
        raise ValueError("A section proposal cannot replace the page title.")
    top = [h for h in parsed if h.level == 2]
    if top:
        if len(top) != 1 or top[0].start != 0 or section_key(top[0].title) != section_key(target):
            raise ValueError("Section proposal contains a different or additional top-level section.")
        content = content[top[0].body_start:]
    if not content.strip():
        raise ValueError("Empty section replacement is not allowed.")
    return content.strip("\r\n")


def section_updates(target: str, content: str) -> list[tuple[str, str]]:
    parsed = headings(content)
    if any(h.level == 1 for h in parsed):
        raise ValueError("A section proposal cannot replace the page title.")
    top = [h for h in parsed if h.level == 2]
    if len(top) <= 1:
        return [(target, section_body(content, target))]
    # Older assessments can group multiple proposed sections in one change.
    # Explicit H2 blocks are unambiguous; do not infer headings from prose.
    if content[:top[0].start].strip():
        raise ValueError("A multi-section proposal cannot have unsectioned introductory content.")
    updates = []
    for index, heading in enumerate(top):
        end = top[index + 1].start if index + 1 < len(top) else len(content)
        updates.append((heading.title, section_body(content[heading.body_start:end], heading.title)))
    return updates


def compose_page(snapshot: WikiSnapshot, result: AgentResult) -> str:
    current = snapshot.content
    parsed = headings(current)
    if sum(h.level == 1 for h in parsed) > 1:
        raise ValueError("Multiple page titles require manual composition.")
    sections = [h for h in parsed if h.level == 2]
    by_name = {section_key(h.title): h for h in sections}
    if len(by_name) != len(sections):
        raise ValueError("Duplicate section headings require manual composition.")
    replacements: list[tuple[int, int, str]] = []
    additions: list[str] = []
    used: set[str] = set()
    newline = "\r\n" if "\r\n" in current else "\n"
    for change in result.proposed_changes:
        if change.target_page != snapshot.path:
            raise ValueError("Proposed update targets a different wiki page.")
        for title, body in section_updates(change.target_section, change.proposed_content):
            key = section_key(title)
            if key in used:
                raise ValueError("Multiple proposals target the same section; cannot choose one silently.")
            used.add(key)
            body = body.replace("\r\n", "\n").replace("\n", newline)
            existing = by_name.get(key)
            if existing:
                end = next((h.start for h in parsed if h.start > existing.start and h.level <= 2), len(current))
                replacements.append((existing.body_start, end, newline + body + newline * 2))
            else:
                additions.append(f"## {title.strip()}{newline}{newline}{body}{newline}")
    # Apply only selected section bodies. Every byte outside those ranges remains.
    for start, end, content in sorted(replacements, reverse=True):
        current = current[:start] + content + current[end:]
    if additions:
        current += ("" if current.endswith(newline * 2) else newline if current.endswith(newline) else newline * 2)
        current += newline.join(additions)
    if len(current) > 16000:
        raise ValueError("Composed page exceeds the approved content limit; no truncation is allowed.")
    return current


def review_notes(snapshot: WikiSnapshot, updated: str, result: AgentResult) -> str:
    diff_lines = difflib.unified_diff(
        snapshot.content.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile="current-wiki", tofile="proposed-wiki",
    )
    diff = "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in diff_lines
    )
    # A fence longer than any source run keeps excerpts from closing the diff.
    longest = max((len(m[0]) for m in re.finditer(r"`+", diff)), default=0)
    fence = "`" * max(3, longest + 1)
    parts = [
        "# Wiki change review", "", f"Target: {snapshot.path}", f"Current page: {snapshot.uri}",
        f"Base ETag: {snapshot.etag}", f"Assessment: {result.request_id}",
        "", "These are review notes, not content to publish to the wiki.",
        "", "## Changes", f"{fence}diff", diff, fence,
        "", "## Findings",
        *[f"- {finding.description}" for finding in result.findings],
        "", "## Information missing",
        *[f"- {item.description} (expected source: {item.expected_source})" for item in result.missing_information],
        "", "## Evidence",
    ]
    for item in result.evidence:
        parts.extend([f"- {item.id}: {item.uri}", f"  Version: {item.version}", f"  {item.excerpt}"])
    return "\n".join(parts) + "\n"
