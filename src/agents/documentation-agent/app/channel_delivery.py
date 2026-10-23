"""One-shot channel creation through the SDK's authenticated connector session."""

import json
import logging
import re
from typing import Any

from microsoft_agents.activity import Activity, Attachment, ConversationParameters, ConversationResourceResponse
from microsoft_agents.hosting.core import TurnContext
from microsoft_agents.hosting.core.connector import ConnectorClientBase
from microsoft_agents.hosting.core.connector.client import ConnectorClient

from .channel_policy import SharedReviewScope
from .teams_card import CARD_TYPE

LOGGER = logging.getLogger(__name__)


def error_detail(raw: bytes) -> str:
    """Keep bounded diagnostic fields, never headers, tokens or arbitrary payloads."""
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return "No JSON error detail."
    error = value.get("error") if isinstance(value, dict) else None
    if not isinstance(error, dict):
        return "No structured error detail."
    message = " ".join(str(error.get(key, ""))[:512] for key in ("code", "message"))
    message = re.sub(r"https?://\S+|[\w.+%-]+@[\w.-]+|[A-Za-z0-9_+/=-]{40,}", "[redacted]", message)
    message = re.sub(r"(?i)(bearer|token|secret|password)\s*[:= ]+\S+", r"\1 [redacted]", message)
    return "".join(c if c.isprintable() else " " for c in message)[:600]


async def create_channel_post(
    context: TurnContext, scope: SharedReviewScope, output: dict[str, Any],
) -> SharedReviewScope:
    connector = context.services.get(ConnectorClientBase)  # type: ignore[type-abstract]
    if not isinstance(connector, ConnectorClient):
        raise ValueError("Authenticated Teams connector unavailable; no channel post attempted.")
    parameters = ConversationParameters(
        is_group=True, agent=context.activity.recipient, tenant_id=str(scope.tenant_id),
        channel_data={
            "tenant": {"id": str(scope.tenant_id)},
            "team": {"id": scope.team_id}, "channel": {"id": scope.channel_id},
        },
        activity=Activity(
            # A separate text body plus a card expands to multiple Teams
            # activities; create-conversation accepts a single root activity.
            type="message",
            attachments=[Attachment(content_type=CARD_TYPE, content=output)],
        ),
    )
    # SDK create_conversation discards HTTP error bodies and leaks its connector
    # on failure. The public client preserves SDK auth; the caller owns cleanup.
    async with connector.client.post(
        "v3/conversations", json=parameters.model_dump(mode="json", by_alias=True, exclude_unset=True),
        allow_redirects=False,
    ) as response:
        raw = await response.content.read(65537)
        if response.status not in {200, 201, 202}:
            detail = error_detail(raw[:65536])
            LOGGER.error("Channel post rejected: HTTP %s; %s", response.status, detail)
            raise ValueError(f"Teams channel post returned HTTP {response.status}: {detail}. No automatic retry.")
        if len(raw) > 65536:
            raise ValueError("Channel creation response exceeded the bound; inspect before retrying.")
        created = ConversationResourceResponse.model_validate_json(raw)
    conversation_id, _, encoded = created.id.partition(";messageid=")
    root_id = encoded or created.activity_id
    if not conversation_id or not root_id:
        raise ValueError("Channel post has no returned thread identity; inspect before retrying.")
    if created.activity_id and encoded and created.activity_id != encoded:
        raise ValueError("Channel post returned conflicting thread identifiers; inspect before retrying.")
    return scope.model_copy(update={"conversation_id": conversation_id, "thread_id": root_id})
