import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from documentation_agent.channel_delivery import create_channel_post, error_detail
from documentation_agent.channel_policy import SharedReviewScope
from microsoft_agents.activity import Activity, ChannelAccount
from microsoft_agents.hosting.core.connector.client import ConnectorClient


@pytest.mark.parametrize("status,payload", [
    (201, {"id": "channel;messageid=root", "activityId": "root"}),
    (400, {"error": {"code": "BadArgument", "message": "Missing activity field"}}),
    (403, {"error": {"code": "Forbidden", "message": "Access denied"}}),
    (201, {"id": "channel"}),
    (201, {"id": "channel;messageid=root", "activityId": "different"}),
])
def test_exact_one_shot_payload_and_thread_result(status, payload):
    closed = []
    response = SimpleNamespace(
        status=status, content=SimpleNamespace(read=AsyncMock(return_value=json.dumps(payload).encode())),
    )

    class Exchange:
        async def __aenter__(self):
            return response

        async def __aexit__(self, *args):
            closed.append(True)

    connector = Mock(spec=ConnectorClient)
    connector.client = SimpleNamespace(post=Mock(return_value=Exchange()))
    context = SimpleNamespace(
        activity=Activity(type="event", recipient=ChannelAccount(id="bot")),
        services=SimpleNamespace(get=lambda _: connector),
    )
    scope = SharedReviewScope(
        tenant_id="00000000-0000-4000-8000-000000000001", team_id="team", channel_id="channel",
        conversation_id="channel", thread_id="registration",
    )
    call = create_channel_post(context, scope, {"type": "AdaptiveCard"})
    if status == 201 and payload.get("activityId") == "root":
        result = asyncio.run(call)
        assert result.thread_id == "root" and result.conversation_id == "channel"
    else:
        with pytest.raises(ValueError):
            asyncio.run(call)
    connector.client.post.assert_called_once()
    args = connector.client.post.call_args
    assert args.args == ("v3/conversations",)
    assert args.kwargs["allow_redirects"] is False
    assert args.kwargs["json"]["channelData"]["channel"]["id"] == "channel"
    assert "text" not in args.kwargs["json"]["activity"]
    assert len(args.kwargs["json"]["activity"]["attachments"]) == 1
    assert "conversation" not in args.kwargs["json"]
    assert closed == [True]


def test_error_detail_is_bounded_and_redacted():
    raw = json.dumps({"error": {
        "code": "BadArgument",
        "message": "token=secret-value person@example.com https://example.com/private " + "a" * 1000,
    }}).encode()
    detail = error_detail(raw)
    assert "BadArgument" in detail and len(detail) <= 600
    for secret in ("secret-value", "person@example.com", "https://example.com", "a" * 40):
        assert secret not in detail
    assert error_detail(b"<html>token=secret</html>") == "No JSON error detail."
