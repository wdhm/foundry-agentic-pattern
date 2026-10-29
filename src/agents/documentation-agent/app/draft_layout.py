"""Generated review paths, shared by publication and approval validation."""

import re
from uuid import UUID

ROOT = "/Drafts/Order Sync"
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
REVIEW = rf"PR-[1-9]\d*/Review-{UUID_PATTERN}"
REVISION = rf"{REVIEW}/Revisions/Revision-{UUID_PATTERN}"


def review_path(event_id: UUID, pr_id: int) -> str:
    if pr_id <= 0:
        raise ValueError("Review requires a positive PR number.")
    return f"{ROOT}/PR-{pr_id}/Review-{event_id}"


def changes_path(draft_path: str) -> str:
    if re.fullmatch(rf"{re.escape(ROOT)}/(?:{REVIEW}|{REVISION})/Draft", draft_path):
        return draft_path.removesuffix("/Draft") + "/Changes"
    # Retain compatibility with pending proposals created before the layout change.
    if re.fullmatch(rf"{re.escape(ROOT)}/PR-[1-9]\d*-{UUID_PATTERN}(?:-revision-{UUID_PATTERN})?", draft_path):
        return draft_path + "-review"
    raise ValueError("Review draft path is not a generated draft location.")


def writable_path(path: str) -> bool:
    return re.fullmatch(
        rf"{re.escape(ROOT)}/(?:PR-[1-9]\d*|{REVIEW}(?:/Revisions)?|{REVISION}|"
        rf"(?:{REVIEW}|{REVISION})/(?:Draft|Changes))", path,
    ) is not None
