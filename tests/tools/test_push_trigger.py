from unittest.mock import Mock
from uuid import uuid4

import pytest

from tools.push_trigger import FoundryPushClient, send_push


def test_concrete_session_binding_invoke_and_stop():
    client = Mock()
    session = {
        "agent_session_id": "pipeline-session", "status": "active",
        "version_indicator": {"type": "version_ref", "agent_version": "42"},
    }
    result = {"event_id": str(uuid4()), "state": "notified", "duplicate": False}
    client.request.side_effect = [session, session, result, {}]
    payload = {"commit_sha": "a" * 40}
    assert send_push(client, "42", payload) == result
    assert client.request.call_args_list[0].args == (
        "POST", "/endpoint/sessions?api-version=v1",
        {"version_indicator": {"type": "version_ref", "agent_version": "42"}},
    )
    assert client.request.call_args_list[2].args == (
        "POST", "/endpoint/protocols/invocations?api-version=v1&agent_session_id=pipeline-session", payload,
    )
    assert client.request.call_args.args == ("POST", "/endpoint/sessions/pipeline-session:stop?api-version=v1")


@pytest.mark.parametrize("problem", ["version", "status", "invoke"])
def test_failure_stops_only_owned_session_without_retry(problem):
    client = Mock()
    session = {
        "agent_session_id": "owned", "status": "active",
        "version_indicator": {"type": "version_ref", "agent_version": "42"},
    }
    if problem == "version":
        bad = {**session, "version_indicator": {"type": "version_ref", "agent_version": "41"}}
        client.request.side_effect = [session, bad, {}]
    elif problem == "status":
        client.request.side_effect = [session, {**session, "status": "failed"}, {}]
    else:
        client.request.side_effect = [session, session, TimeoutError("unknown"), {}]
    with pytest.raises((ValueError, TimeoutError)):
        send_push(client, "42", {})
    assert client.request.call_args.args == ("POST", "/endpoint/sessions/owned:stop?api-version=v1")
    assert client.request.call_count == (4 if problem == "invoke" else 3)


@pytest.mark.parametrize("version", ["latest", "@latest", "0", "../42"])
def test_no_floating_or_invalid_version(version):
    client = Mock()
    with pytest.raises(ValueError):
        send_push(client, version, {})
    client.request.assert_not_called()


def test_client_rejects_arbitrary_token_destinations():
    with pytest.raises(ValueError):
        FoundryPushClient("https://attacker.example/project", "documentation-agent")
    with pytest.raises(ValueError):
        FoundryPushClient("https://test.services.ai.azure.com/api/projects/test", "../agent")
