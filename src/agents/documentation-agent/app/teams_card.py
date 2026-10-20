"""Native Teams review cards; exact proposal first, explicit decisions last."""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from .approval import PendingCall

CARD_TYPE = "application/vnd.microsoft.card.adaptive"
MAX_CARD_BYTES = 26000


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
    body = [
        text(titles[status], weight="Bolder", size="Medium"),
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
    ]
    if view == "edit" and pending:
        body += [
            text("Revise the proposal", weight="Bolder"),
            text("Saving invalidates the old proposal. The new text still requires a separate approval."),
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
        actions = [
            action(record, "modify", "New proposal", inputs=True),
            action(record, "inspect", "Cancel edit"),
        ]
    else:
        body += [text("Proposed content (exact)", weight="Bolder"), text(str(record.arguments[content_parameter]))]
        actions = (
            [action(record, "approve", "Approve"), action(record, "edit", "Modify"), action(record, "reject", "Reject")]
            if pending
            else []
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
