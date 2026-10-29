"""Native Teams review cards; exact proposal first, explicit decisions last."""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from .approval import PendingCall

CARD_TYPE = "application/vnd.microsoft.card.adaptive"
MAX_CARD_BYTES = 26000


def status_header(status: str, *, title: str | None = None) -> dict[str, Any]:
    states = {
        "pending": ("◷", "Ready for review", "Accent"),
        "executing": ("↻", "Publishing — awaiting confirmation", "Accent"),
        "succeeded": ("✓", "Published", "Good"),
        "rejected": ("×", "Rejected — not published", "Default"),
        "modified": ("↻", "Replaced by a new proposal", "Default"),
        "expired": ("!", "Review expired", "Warning"),
        "outcome_unknown": ("!", "Publication outcome unknown", "Attention"),
    }
    icon, label, color = states[status]
    return {
        "type": "RichTextBlock",
        "inlines": [{
            "type": "TextRun", "text": f"{icon}  {title or label}",
            "weight": "Bolder", "size": "Medium", "color": color,
        }],
    }


def secondary(value: str) -> dict[str, Any]:
    return {"type": "TextBlock", "text": value, "wrap": True, "size": "Small", "isSubtle": True}


def text(value: str, *, weight: str = "Default", size: str = "Default") -> dict[str, Any]:
    # TextRun is plain text: source/proposal Markdown cannot hide the exact content.
    return {
        "type": "RichTextBlock",
        "inlines": [{"type": "TextRun", "text": value, "weight": weight, "size": size}],
    }


def card(body: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": body,
    }
    if actions:
        result["actions"] = actions
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_CARD_BYTES:
        raise ValueError(
            "The full proposal exceeds the Teams card size limit; use the authenticated Responses interface."
        )
    return result


def action(record: PendingCall, verb: str, title: str, *, inputs: bool = False) -> dict[str, Any]:
    return {
        "type": "Action.Submit",
        "title": title,
        "associatedInputs": "auto" if inputs else "none",
        "data": {
            "interface_version": "1.0.0",
            "action": verb,
            "pending_id": str(record.pending_id),
            "args_hash": record.args_hash,
        },
    }


def linked_review_card(
    record: PendingCall, draft_link: str, pr_link: str, target: str, findings: int, missing: int,
    *, matches_draft: bool, page_update: bool = False, notes_link: str | None = None,
    wiki_draft: bool = False,
) -> dict[str, Any]:
    pending = record.status == "pending" and record.expires_at > datetime.now(UTC)
    status = "expired" if record.status == "pending" and not pending else record.status
    body = [
        status_header(
            status, title="Review documentation draft" if pending else f"Documentation proposal: {status}",
        ),
        text(f"Target: {target}"),
        text(f"Findings: {findings}; missing facts: {missing}."),
        text(
            "The published page was verified against the approved content."
            if status == "succeeded" and record.result and record.result.get("wiki_readback") else
            "The tool reported success. Check the published destination."
            if status == "succeeded" else
            "No publication was approved. The draft is retained for reference."
            if status == "rejected" else
            "Use the replacement proposal; this card can no longer authorize publication."
            if status == "modified" else
            "This review expired. Generate a fresh proposal before publishing."
            if status == "expired" else
            "Do not approve again. Publication has started but is not yet confirmed."
            if status in {"executing", "outcome_unknown"} else
            "Read the exact draft before approving. The update is bound to the wiki version used to create it."
            if page_update and matches_draft else
            "Read the linked, commit-pinned draft before approving. Approval writes that exact content to the sandbox."
            if matches_draft else
            "You edited this proposal. The original draft link no longer represents the new text. Review the revision."
        ),
    ]
    links = [{"type": "Action.OpenUrl", "title": "Merged PR", "url": pr_link}]
    if matches_draft:
        links.insert(0, {
            "type": "Action.OpenUrl", "title": "Draft page" if wiki_draft else "View draft", "url": draft_link,
        })
        if notes_link:
            links.insert(1, {"type": "Action.OpenUrl", "title": "Changes", "url": notes_link})
    body.append({"type": "ActionSet", "actions": links})
    body.append(text(f"Expires: {record.expires_at.astimezone(UTC):%d %b %Y %H:%M} UTC"))
    body.append(text(f"Pending: {record.pending_id}"))
    if pending and matches_draft:
        actions = [
            action(record, "approve", "Approve"), action(record, "edit", "Modify"), action(record, "reject", "Reject"),
        ]
    elif pending:
        actions = [action(record, "details", "Review revision"), action(record, "reject", "Reject")]
    else:
        actions = [action(record, "inspect", "Refresh status")]
        if status in {"executing", "outcome_unknown"}:
            body.append(text("Outcome is uncertain. Inspect the target; do not retry the write."))
    return card(body, actions)


def review_card(
    record: PendingCall, content_parameter: str, *, view: Literal["review", "edit"] = "review"
) -> dict[str, Any]:
    expired = record.expires_at <= datetime.now(UTC)
    pending = record.status == "pending" and not expired
    status = "expired" if record.status == "pending" and expired else record.status
    titles = {
        "pending": "Review proposed update",
        "expired": "Approval expired",
        "rejected": "Proposal rejected",
        "modified": "Original proposal replaced",
        "executing": "Execution started - outcome not confirmed",
        "succeeded": "Tool reported success",
        "outcome_unknown": "Outcome unknown - do not retry",
    }
    if view == "edit" and pending:
        target = record.arguments.get("path") or (record.origin.target_page if record.origin else None)
        # Editing is not approval: keep the full evidence and tool details on
        # the review screen, not between the editor and its submit button.
        body = [
            status_header("pending", title="Modify documentation draft"),
            *([text(f"Target: {target}")] if isinstance(target, str) else []),
            text("Edit the complete draft below. New proposal replaces this proposal; "
                 "publishing still needs a separate approval."),
            {
                "type": "Input.Text",
                "id": "content",
                "label": "Complete replacement content",
                "isMultiline": True,
                "isRequired": True,
                "maxLength": 16000,
                "errorMessage": "Enter the complete proposed content.",
                "value": record.arguments[content_parameter],
            },
            {
                "type": "Input.Text",
                "id": "feedback",
                "label": "Reason for the change",
                "isRequired": True,
                "maxLength": 1000,
                "errorMessage": "Explain the change before creating a new proposal.",
            },
        ]
        return card(body, [
            action(record, "modify", "New proposal", inputs=True),
            action(record, "inspect", "Cancel edit"),
        ])
    body = [
        status_header(status, title=titles[status]),
        text(
            "No write until you approve. Approval attempts the exact call below once."
            if pending
            else "This card cannot authorize another execution. Inspect the target if the outcome is uncertain."
        ),
        text(f"Tool: {record.tool}"),
        text("Target and fixed arguments", weight="Bolder"),
        text(json.dumps(
            {k: v for k, v in record.arguments.items() if k != content_parameter}, ensure_ascii=False, indent=2
        )),
        text("Proposed content (exact)", weight="Bolder"), text(str(record.arguments[content_parameter])),
    ]
    actions = (
        [action(record, "approve", "Approve"), action(record, "edit", "Modify"), action(record, "reject", "Reject")]
        if pending else []
    )
    body += [
        text("Evidence", weight="Bolder"),
        text("Supplied with the proposal; this approval screen does not independently verify the source."),
    ]
    for evidence in record.evidence:
        body += [
            text(f"{evidence.source} - {evidence.id}", weight="Bolder"),
            text(evidence.uri),
            text(f"Version: {evidence.version}"),
            text(evidence.excerpt),
        ]
    body += [
        text(f"Run: {record.run_id}"),
        text(f"Pending: {record.pending_id}"),
        text(f"Arguments SHA-256: {record.args_hash}"),
        text(f"Expires (UTC): {record.expires_at.astimezone(UTC).isoformat()}"),
    ]
    if record.origin:
        body.append(text(f"Original assessment: {record.origin.request_id}; proposal {record.origin.proposal_index}"))
    if record.decided_at:
        body.append(text(f"Decision recorded (UTC): {record.decided_at.astimezone(UTC).isoformat()}"))
    if record.replacement_id:
        body.append(text(f"Replacement pending ID: {record.replacement_id}"))
    if not pending:
        actions = [action(record, "inspect", "Refresh status")]
    return card(body, actions)
