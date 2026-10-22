from unittest.mock import Mock
from uuid import uuid4

import pytest

from contracts.drafts import PreparedDraft, content_hash, draft_branch, draft_path, draft_url, review_path
from tools.merged_pr import AzureDraftClient, NoRedirect
from tools.push_trigger import send_merged_pr, send_push

REPO_ID = "00000000-0000-4000-8000-000000000004"
REPO = f"https://dev.azure.com/test/project/_git/{REPO_ID}"
SOURCE = "a" * 40
DRAFT = "b" * 40


def pr(**changes):
    return {
        "pullRequestId": 12, "status": "completed", "mergeStatus": "succeeded",
        "targetRefName": "refs/heads/main", "lastMergeCommit": {"commitId": SOURCE},
        "repository": {"id": REPO_ID}, **changes,
    }


def test_completed_pr_exact_result_commit_and_no_message_guess():
    client = AzureDraftClient(REPO)
    client.request = Mock(side_effect=[{"value": [pr()]}, pr()])
    assert client.completed_pr(SOURCE) == 12
    assert client.request.call_args.args == ("GET", "/pullrequests/12?api-version=7.1")


def test_direct_push_or_open_pr_does_not_trigger_foundry(monkeypatch):
    source = Mock()
    source.completed_pr.return_value = None
    monkeypatch.setattr("tools.merged_pr.AzureDraftClient", lambda _: source)
    foundry = Mock()
    assert send_merged_pr(foundry, "42", {"repository_url": REPO, "commit_sha": SOURCE}) == {
        "state": "skipped", "reason": "not_a_completed_pr_merge", "assessment_run": False,
    }
    source.publish.assert_not_called()
    foundry.request.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"status": "active"}, {"status": "abandoned"}, {"mergeStatus": "conflicts"},
        {"targetRefName": "refs/heads/feature"}, {"lastMergeCommit": {"commitId": "c" * 40}},
        {"repository": {"id": str(uuid4())}},
    ],
)
def test_pr_readback_must_confirm_merge(change):
    client = AzureDraftClient(REPO)
    client.request = Mock(side_effect=[{"value": [pr()]}, pr(**change)])
    with pytest.raises(ValueError, match="successful merge"):
        client.completed_pr(SOURCE)


def test_completed_pr_pagination_and_ambiguity():
    client = AzureDraftClient(REPO)
    client.request = Mock(side_effect=[
        {"value": [pr(lastMergeCommit={"commitId": "c" * 40}) for _ in range(100)]},
        {"value": [pr()]},
        pr(),
    ])
    assert client.completed_pr(SOURCE) == 12
    assert "%24skip=100" in client.request.call_args_list[1].args[1]
    client.request = Mock(return_value={"value": [pr(), pr(pullRequestId=13)]})
    with pytest.raises(ValueError, match="multiple"):
        client.completed_pr(SOURCE)


@pytest.fixture
def prepared():
    content = "# Documentation draft\n\nProposed text with evidence.\n"
    return PreparedDraft(
        event_id=uuid4(), state="draft_ready", duplicate=False, content=content, content_sha256=content_hash(content),
        source_commit=SOURCE, pull_request_id=12,
    )


def test_publish_only_draft_ref_exact_bytes_and_read_back(prepared):
    client = AzureDraftClient(REPO)
    client.request = Mock(side_effect=[
        {"value": []}, {"pushId": 1},
        {"value": [{"name": draft_branch(prepared.event_id), "objectId": DRAFT}]},
        {"parents": [SOURCE]}, {"content": prepared.content},
    ])
    assert client.publish(prepared) == DRAFT
    method, path, body = client.request.call_args_list[1].args
    assert method == "POST" and path == "/pushes?api-version=7.1"
    assert body["refUpdates"] == [{"name": draft_branch(prepared.event_id), "oldObjectId": "0" * 40}]
    commit = body["commits"][0]
    assert commit["parents"] == [SOURCE]
    assert len(commit["changes"]) == 1
    assert commit["changes"][0]["item"]["path"] == draft_path(prepared.event_id)
    assert commit["changes"][0]["newContent"]["content"] == prepared.content
    assert "versionDescriptor.versionType=commit" in client.request.call_args.args[1]
    assert DRAFT in client.request.call_args.args[1]


def test_recover_existing_exact_draft_without_mutation(prepared):
    client = AzureDraftClient(REPO)
    client.request = Mock(side_effect=[
        {"value": [{"name": draft_branch(prepared.event_id), "objectId": DRAFT}]},
        {"parents": [SOURCE]}, {"content": prepared.content},
    ])
    assert client.publish(prepared) == DRAFT
    assert all(call.args[0] == "GET" for call in client.request.call_args_list)


@pytest.mark.parametrize("changed", ["parent", "content", "hash"])
def test_never_overwrite_changed_draft(prepared, changed):
    client = AzureDraftClient(REPO)
    client.request = Mock(side_effect=[
        {"value": [{"name": draft_branch(prepared.event_id), "objectId": DRAFT}]},
        {"parents": ["c" * 40] if changed == "parent" else [SOURCE]},
        {"content": "changed" if changed == "content" else prepared.content},
    ])
    if changed == "hash":
        prepared.content_sha256 = "f" * 64
    with pytest.raises(ValueError):
        client.publish(prepared)
    assert all(call.args[0] == "GET" for call in client.request.call_args_list)


def test_draft_link_is_commit_not_branch(prepared):
    url = draft_url(REPO, prepared.event_id, DRAFT)
    assert "version=GC" + DRAFT in url
    assert "GB" not in url
    assert str(prepared.event_id) in url


def test_missing_job_token_and_redirect_fail_closed(monkeypatch):
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN", raising=False)
    client = AzureDraftClient(REPO)
    with pytest.raises(ValueError, match="SYSTEM_ACCESSTOKEN"):
        client.request("GET", "/refs?api-version=7.1")
    with pytest.raises(ValueError, match="redirect"):
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.example")


def test_prepare_publish_finalize_pipeline_sequence(prepared, monkeypatch):
    source = Mock()
    source.completed_pr.return_value = 12
    source.publish.return_value = DRAFT
    monkeypatch.setattr("tools.merged_pr.AzureDraftClient", lambda _: source)
    send = Mock(side_effect=[
        prepared.model_dump(mode="json"),
        {"event_id": str(prepared.event_id), "state": "notified", "duplicate": False},
    ])
    monkeypatch.setattr("tools.push_trigger.send_push", send)
    payload = {"repository_url": REPO, "commit_sha": SOURCE}
    assert send_merged_pr(Mock(), "42", payload)["state"] == "notified"
    assert send.call_args_list[0].args[2] == {**payload, "pull_request_id": 12}
    assert send.call_args_list[1].args[2] == {
        "interface_version": "1.0.0", "action": "draft_published",
        "event_id": str(prepared.event_id), "draft_commit": DRAFT,
    }
    source.publish.assert_called_once()


def test_prepared_wrong_correlation_stops_session(prepared):
    client = Mock()
    session = {
        "agent_session_id": "test", "status": "active",
        "version_indicator": {"type": "version_ref", "agent_version": "42"},
    }
    client.request.side_effect = [session, session, prepared.model_dump(mode="json"), {}]
    with pytest.raises(ValueError, match="match the submitted"):
        send_push(client, "42", {"commit_sha": "c" * 40, "pull_request_id": 12})
    assert client.request.call_args.args == ("POST", "/endpoint/sessions/test:stop?api-version=v1")


def test_final_page_and_review_notes_are_separate_pinned_files(prepared):
    prepared.review_notes = "# Changes\n\nEvidence and diff."
    client = AzureDraftClient(REPO)
    client.request = Mock(side_effect=[
        {"value": []}, {"pushId": 1},
        {"value": [{"name": draft_branch(prepared.event_id), "objectId": DRAFT}]},
        {"parents": [SOURCE]}, {"content": prepared.content}, {"content": prepared.review_notes},
    ])
    assert client.publish(prepared) == DRAFT
    changes = client.request.call_args_list[1].args[2]["commits"][0]["changes"]
    assert [(item["item"]["path"], item["newContent"]["content"]) for item in changes] == [
        (draft_path(prepared.event_id), prepared.content), (review_path(prepared.event_id), prepared.review_notes),
    ]
    assert "version=GC" + DRAFT in draft_url(REPO, prepared.event_id, DRAFT, review=True)
