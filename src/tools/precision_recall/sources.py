"""Discover complete pinned trees, cache immutable reads, and prepare safe local text."""

import difflib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from contracts.repositories import AzureRepository
from tools.ado_transport import JsonGet, SandboxError
from tools.release_sources import blob_id
from tools.sandbox_eval import approve_identity, check_identity, digest

from .models import Case, Config, Manifest, Repo, valid_path

REDACTION_VERSION = "2"
SECRET = re.compile(
    r"""(?ix)
    (?<![\w.-])(?P<key>["']?(?:[\w.-]*(?:password|passwd|secret|connectionstring|accountkey|accesskey|api[_-]?key|
    sharedaccesssignature|clientsecret|access_token|refresh_token|bearer_token)[\w.-]*)["']?\s*[:=]\s*)
    (?P<value>"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}\r\n]+)
    """
)
SAS = re.compile(r"(?i)([?&](?:sig|signature)=)[^&\s\"'<>]+")
HIGH_RISK = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
)


def redact(text: str) -> str:
    # Connection strings can contain several semicolon-separated credentials.
    text = re.sub(
        r"(?i)\b(?:DefaultEndpointsProtocol|Server|Data Source)=[^\r\n\"']*"
        r"(?:AccountKey|Password|Pwd)=[^\r\n\"']*",
        "<REDACTED>", text,
    )
    text = SECRET.sub(lambda m: m["key"] + '"<REDACTED>"', text)
    text = SAS.sub(lambda m: m[1] + "<REDACTED>", text)
    if HIGH_RISK.search(text):
        raise SandboxError("Known credential material detected; source/output blocked.")
    return text


def safe_text(text: str) -> None:
    if redact(text) != text:
        raise SandboxError("Unredacted credential-like values detected; output blocked.")


def safe_value(value: Any) -> None:
    if isinstance(value, str):
        safe_text(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            safe_value(key)
            safe_value(item)
    elif isinstance(value, list):
        for item in value:
            safe_value(item)


def private_json(path: Path, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n"
    safe_value(value)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8") as file:
        file.write(text)


def api(repo: Repo | AzureRepository, operation: str, query: dict[str, str]) -> str:
    prefix = "/".join(quote(p, safe="") for p in (
        repo.organization, repo.project, "_apis", "git", "repositories", repo.repository,
    ))
    return "https://dev.azure.com/" + prefix + "/" + operation + "?" + urlencode({"api-version": "7.1", **query})


def item_uri(repo: Repo, path: str) -> str:
    return api(repo, "items", {
        "path": valid_path(path), "versionDescriptor.version": repo.commit,
        "versionDescriptor.versionType": "commit", "includeContent": "true",
    })


def tree_uri(repo: Repo) -> str:
    return api(repo, "items", {
        "scopePath": "/", "recursionLevel": "Full", "includeContentMetadata": "true",
        "versionDescriptor.version": repo.commit, "versionDescriptor.versionType": "commit",
    })


def diff_uri(case: Case) -> str:
    return api(case.integration_repo, "diffs/commits", {
        "baseVersion": case.base_commit, "baseVersionType": "commit",
        "targetVersion": case.merge_commit, "targetVersionType": "commit", "$top": "10000",
    })


def label(repo: Repo, path: str) -> str:
    return f"{repo.id}@{repo.commit}:{path}"


class Reader:
    def __init__(
        self, manifest: Manifest, config: Config, cache: Path,
        get: Callable[[str], tuple[dict[str, Any], dict[str, str]]],
        allowed: set[str],
    ) -> None:
        self.manifest, self.config, self.cache, self.get, self.allowed = manifest, config, cache, get, allowed
        self.bytes = 0
        self.repo_keys = {
            repo.key for case in manifest.cases for repo in [
                *case.repos, case.page.repo, case.integration_repo.model_copy(update={"commit": case.base_commit}),
            ]
        }

    @classmethod
    def authenticated(
        cls, manifest: Manifest, config: Config, cache: Path, token: str, *, manual_user_approved: bool,
    ) -> "Reader":
        approve_identity(manifest.read_identity, manual_user_approved)
        check_identity(token, manifest.read_identity)
        allowed: set[str] = set()
        transport = JsonGet(token, allowed, config.max_requests, max_bytes=2_000_000)
        return cls(manifest, config, cache, transport.get, allowed)

    def cached(self, repo: Repo, operation: str, uri: str) -> dict[str, Any]:
        if repo.key not in self.repo_keys:
            raise SandboxError("Repository/commit is outside the approved manifest.")
        key = digest(REDACTION_VERSION + repo.key + operation)
        coordinates = repo.model_dump(exclude={"id"})
        path = self.cache / (key + ".json")
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if (
                saved["key"] != key or saved["repo"] != coordinates
                or saved["sha256"] != digest(json.dumps(saved["payload"], sort_keys=True))
            ):
                raise SandboxError("Pinned source cache integrity mismatch.")
            safe_value(saved["payload"])
            return dict(saved["payload"])
        self.allowed.add(uri)
        payload, headers = self.get(uri)
        if headers.get("x-ms-continuationtoken") or headers.get("x-ms-continuation-token"):
            raise SandboxError("Truncated source discovery; raise reviewed limits or narrow declared repositories.")
        if operation.startswith("file:"):
            content = payload.get("content")
            if (
                payload.get("path") != operation[5:] or payload.get("commitId") != repo.commit
                or not isinstance(content, str) or payload.get("objectId") != blob_id(content)
            ):
                raise SandboxError("File response does not match pinned path, commit and blob.")
            payload = {
                "path": payload["path"], "commit": repo.commit, "blob": payload["objectId"],
                "source_sha256": digest(content), "content": redact(content),
            }
        safe_value(payload)
        private_json(path, {
            "key": key, "repo": coordinates, "payload": payload,
            "captured_at": datetime.now(UTC).isoformat(),
            "sha256": digest(json.dumps(payload, sort_keys=True)),
        })
        return payload

    def file(self, repo: Repo, path: str) -> str:
        text = self.cached(repo, "file:" + path, item_uri(repo, path))["content"]
        if not isinstance(text, str) or "\x00" in text or text.startswith("version https://git-lfs.github.com/spec/"):
            raise SandboxError("Binary or LFS source cannot be evaluated as code.")
        self.bytes += len(text.encode())
        if self.bytes > self.config.max_source_bytes:
            raise SandboxError("Complete source capture exceeds the approved byte budget.")
        return text

    def tree(self, repo: Repo) -> tuple[list[str], list[str]]:
        payload = self.cached(repo, "tree", tree_uri(repo))
        items = payload.get("value")
        if not isinstance(items, list) or payload.get("count") != len(items) or not items:
            raise SandboxError("Invalid or empty pinned tree discovery response.")
        if len(items) > self.config.max_files:
            raise SandboxError("Complete repository exceeds the approved item budget; no partial discovery.")
        paths, excluded = [], []
        seen = set()
        for item in items:
            if item.get("commitId") != repo.commit:
                raise SandboxError("Discovered item commit differs from the requested pin.")
            if item.get("isFolder"):
                continue
            path = valid_path(item["path"])
            if path in seen:
                raise SandboxError("Duplicate path in source discovery.")
            seen.add(path)
            if item.get("gitObjectType") != "blob":
                raise SandboxError("Submodules require explicit related-repository pins; capture stopped.")
            if item.get("contentMetadata", {}).get("isBinary"):
                excluded.append(path)
            else:
                paths.append(path)
        if len(paths) > self.config.max_files:
            raise SandboxError("Complete repository exceeds the approved file budget; no partial discovery.")
        return sorted(paths), sorted(excluded)

    def capture(self) -> dict[str, Any]:
        cases: list[dict[str, Any]] = []
        for case in self.manifest.cases:
            files, exclusions = {}, {}
            for repo in case.repos:
                paths, excluded = self.tree(repo)
                exclusions[repo.id] = excluded
                for path in paths:
                    files[label(repo, path)] = self.file(repo, path)
            diff = self.cached(case.integration_repo, "diff:" + case.base_commit, diff_uri(case))
            if diff.get("allChangesIncluded") is not True:
                raise SandboxError("Merge diff is incomplete.")
            touched: list[str] = []
            patches: list[str] = []
            base_files: dict[str, str] = {}
            base = case.integration_repo.model_copy(update={"commit": case.base_commit})
            for change in diff["changes"]:
                path = valid_path(change["item"]["path"])
                if change["item"].get("isFolder"):
                    continue
                kind = change["changeType"].lower()
                if kind not in {"add", "edit", "delete", "rename", "rename, edit"}:
                    raise SandboxError("Unsupported diff change; no incomplete fallback.")
                old_path = valid_path(change.get("originalPath", path))
                before = "" if kind == "add" else self.file(base, old_path)
                after = "" if kind == "delete" else files.get(label(case.integration_repo, path))
                if after is None:
                    raise SandboxError("Changed file was excluded or missing from complete code discovery.")
                if kind != "add":
                    base_files[label(base, old_path)] = before
                touched.append(label(case.integration_repo, path))
                patches.extend(difflib.unified_diff(
                    before.splitlines(), after.splitlines(),
                    fromfile=label(base, old_path), tofile=label(case.integration_repo, path), lineterm="",
                ))
            page = self.file(case.page.repo, case.page.path)
            if not page.strip():
                raise SandboxError("Empty wiki page cannot produce a passing evaluation.")
            for fact in case.critical_facts:
                quote_line = fact.source
                lines = files.get(quote_line.file, "").splitlines()
                if (
                    not 1 <= quote_line.line <= len(lines) or lines[quote_line.line - 1] != quote_line.text
                ):
                    raise SandboxError("Engineer fact source does not match pinned, sanitized code.")
            cases.append({
                "case": case.model_dump(mode="json"), "files": files, "binary_exclusions": exclusions,
                "page": page, "page_file": label(case.page.repo, case.page.path),
                "touched": sorted(set(touched)), "diff": "\n".join(patches), "base_files": base_files,
            })
        result = {
            "kind": "pinned_ado_precision_recall_capture", "schema_version": "1",
            "manifest_sha256": digest(self.manifest.model_dump_json()), "redaction_version": REDACTION_VERSION,
            "read_identity": self.manifest.read_identity.model_dump(mode="json"), "cases": cases,
            "source_hashes": {c["case"]["id"]: {
                name: digest(content) for name, content in {**c["files"], c["page_file"]: c["page"]}.items()
            } for c in cases},
        }
        result["sha256"] = digest(json.dumps(result, sort_keys=True))
        return result


def validate_capture(value: dict[str, Any], manifest: Manifest) -> None:
    raw = {k: v for k, v in value.items() if k != "sha256"}
    if (
        value.get("kind") != "pinned_ado_precision_recall_capture" or value.get("schema_version") != "1"
        or value.get("sha256") != digest(json.dumps(raw, sort_keys=True))
        or value.get("manifest_sha256") != digest(manifest.model_dump_json())
        or value.get("redaction_version") != REDACTION_VERSION
        or [c["case"] for c in value["cases"]] != [c.model_dump(mode="json") for c in manifest.cases]
    ):
        raise SandboxError("Capture integrity or manifest provenance mismatch.")
    for data, case in zip(value["cases"], manifest.cases, strict=True):
        if not data["page"].strip() or data["page_file"] != label(case.page.repo, case.page.path):
            raise SandboxError("Capture page provenance is invalid or empty.")
        prefixes = tuple(f"{r.id}@{r.commit}:/" for r in case.repos)
        if not data["files"] or any(not name.startswith(prefixes) for name in data["files"]):
            raise SandboxError("Captured code is outside the manifest repository pins.")
        for fact in case.critical_facts:
            quote_line = fact.source
            lines = data["files"].get(quote_line.file, "").splitlines()
            if (
                not 1 <= quote_line.line <= len(lines) or lines[quote_line.line - 1] != quote_line.text
            ):
                raise SandboxError("Captured fixed fact source is not an exact pinned code line.")
    safe_value(value)
