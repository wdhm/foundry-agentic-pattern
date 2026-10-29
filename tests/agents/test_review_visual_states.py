from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from documentation_agent.approval import PendingCall
from documentation_agent.draft_layout import changes_path, review_path, writable_path
from documentation_agent.teams_card import linked_review_card, review_card


@pytest.mark.parametrize("status,color,label", [
    ("pending", "Accent", "Ready for review"), ("executing", "Accent", "Publishing"),
    ("succeeded", "Good", "Published"), ("rejected", "Default", "Rejected"),
    ("modified", "Default", "Replaced"), ("expired", "Warning", "Review expired"),
    ("outcome_unknown", "Attention", "outcome unknown"),
])
def test_state_color_is_paired_with_readable_text_and_correct_actions(status, color, label):
    now = datetime.now(UTC)
    pending = PendingCall(
        run_id=uuid4(), tool="ado___wiki_upsert_page", arguments={"content": "Reviewed page"},
        args_hash="a" * 64, policy_hash="b" * 64, tool_hash="c" * 64, evidence=[],
        owner="test", session_id="test", created_at=now,
        expires_at=now + timedelta(hours=-1 if status == "expired" else 1),
        status="pending" if status == "expired" else status,
    )
    if status == "succeeded":
        pending.result = {"wiki_readback": {"uri": "https://dev.azure.com/test/published"}}
    output = linked_review_card(
        pending, "https://dev.azure.com/test/draft", "https://dev.azure.com/test/pr",
        "/Overview", 2, 3, matches_draft=True, page_update=True, wiki_draft=True,
    )
    heading = output["body"][0]["inlines"][0]
    assert heading["color"] == color
    expected = "Review documentation draft" if status == "pending" else f"Documentation proposal: {status}"
    assert expected in heading["text"]
    assert output["body"][0]["type"] == "RichTextBlock"
    assert any(f"Pending: {pending.pending_id}" in str(b) for b in output["body"])
    assert any("Expires:" in str(b) for b in output["body"])
    actions = [a["title"] for a in output["actions"]]
    assert actions == (["Approve", "Modify", "Reject"] if status == "pending" else ["Refresh status"])
    if status == "succeeded":
        link_groups = [b for b in output["body"] if b["type"] == "ActionSet"]
        assert len(link_groups) == 1
        assert not any("Read the exact draft before approving" in str(b) for b in output["body"])


def test_layout_accepts_only_generated_containers_and_pairs():
    event, revision = uuid4(), uuid4()
    root = review_path(event, 6)
    draft = root + "/Draft"
    revised = f"{root}/Revisions/Revision-{revision}/Draft"
    assert changes_path(draft) == root + "/Changes"
    assert changes_path(revised) == revised.removesuffix("/Draft") + "/Changes"
    assert writable_path(draft) and writable_path(revised) and writable_path(root)
    legacy = f"/Drafts/Order Sync/PR-6-{event}"
    assert changes_path(legacy) == legacy + "-review"
    assert not writable_path(legacy)  # legacy is readable, never newly published
    for path in ["/Order Sync/Overview", root + "/../Overview", root + "/Draft/Child", "/Drafts/Other"]:
        assert not writable_path(path)
        with pytest.raises(ValueError):
            changes_path(path)


def test_modify_is_a_compact_editor_not_another_review_report():
    record = PendingCall(
        run_id=uuid4(), tool="ado___wiki_upsert_page",
        arguments={"path": "/Order Sync/Overview", "content": "# Page\n\n" + "x" * 15000,
                   "project": "test", "etag": "e" * 40},
        args_hash="a" * 64, policy_hash="b" * 64, tool_hash="c" * 64,
        evidence=[{"id": "e", "source": "git", "uri": "https://example.com/source",
                   "version": "d" * 40, "excerpt": "Detailed source evidence"}],
        owner="test", session_id="test", created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    before = record.model_dump_json()
    edit = review_card(record, "content", view="edit")
    assert len(edit["body"]) == 5
    assert "Modify documentation draft" in edit["body"][0]["inlines"][0]["text"]
    assert edit["body"][1]["inlines"][0]["text"] == "Target: /Order Sync/Overview"
    assert "separate approval" in edit["body"][2]["inlines"][0]["text"]
    fields = {b["id"]: b for b in edit["body"] if b["type"] == "Input.Text"}
    assert fields["content"]["value"] == record.arguments["content"]
    assert fields["content"]["maxLength"] == 16000 and fields["content"]["isMultiline"]
    assert fields["feedback"]["isRequired"] and fields["feedback"]["maxLength"] == 1000
    assert all(field["label"] and field["errorMessage"] for field in fields.values())
    assert [a["title"] for a in edit["actions"]] == ["New proposal", "Cancel edit"]
    assert [a["associatedInputs"] for a in edit["actions"]] == ["auto", "none"]
    assert all(a["data"]["args_hash"] == record.args_hash for a in edit["actions"])
    assert record.model_dump_json() == before
    assert "Detailed source evidence" not in str(edit) and record.tool not in str(edit)
    assert "Arguments SHA-256" not in str(edit) and "Run:" not in str(edit)
    full = review_card(record, "content")
    assert "Detailed source evidence" in str(full) and record.tool in str(full)
    record.status = "rejected"
    closed = review_card(record, "content", view="edit")
    assert not any(b["type"] == "Input.Text" for b in closed["body"])
    assert [a["title"] for a in closed["actions"]] == ["Refresh status"]
