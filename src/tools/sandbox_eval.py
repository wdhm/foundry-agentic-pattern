"""GET-only Azure DevOps capture followed by bounded, isolated, real assessment/judges."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.evaluation import EvaluationRequest, SourceSnapshot, SuppliedStandard
from contracts.repositories import AzureRepository, azure_file_uri
from contracts.v1 import AgentRequest, AssessmentTask
from tools.release_sources import blob_id

if TYPE_CHECKING:
    from tools.eval_loop import LoopConfig
    from tools.release import FoundryEvaluation

ROOT = Path(__file__).resolve().parents[2]
ADO_AUDIENCE = "499b84ac-1321-427f-aa17-267ca6975798"
MAX_RESPONSE_BYTES = 200_000
MAX_SOURCE_BYTES = 80_000
Pin = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SandboxError(ValueError):
    """Fixed local diagnostic text, safe to show without upstream payloads."""


def restricted_output(output: Path) -> Path:
    root = ROOT.resolve()
    resolved = output.expanduser().resolve()
    if resolved.is_relative_to(root):
        relative = resolved.relative_to(root)
        if not relative.is_relative_to(Path("evals") / "results") or relative == Path("evals") / "results":
            raise SandboxError("Repository output must be a new path within ignored evals/results.")
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", relative.as_posix()],
            cwd=root, check=True, capture_output=True,
        )
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative.as_posix()],
            cwd=root, capture_output=True,
        )
        if tracked.stdout or ignored.returncode != 0:
            raise SandboxError("Repository output must be ignored and contain no tracked paths.")
    if resolved.exists():
        raise SandboxError("Output already exists; refusing to overwrite evidence.")
    return resolved


class ReadIdentity(StrictModel):
    tenant_id: UUID
    object_id: UUID
    client_id: UUID


class SandboxPlan(StrictModel):
    organization: Name
    project: Name
    repository: Name
    commit: Pin
    paths: Annotated[list[str], Field(min_length=1, max_length=5)]
    wiki: Name
    wiki_path: str
    wiki_commit: Pin
    wiki_etag: Pin
    read_identity: ReadIdentity
    read_approval_reference: Annotated[str, Field(min_length=1)]
    question: Annotated[str, Field(min_length=1, max_length=8000)]
    scope: Literal["change_review", "information_review"]
    expected_status: Literal["up_to_date", "gaps_found", "insufficient_information"]
    expectation_review_reference: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def bounded_paths(self) -> Self:
        if len(set(self.paths)) != len(self.paths):
            raise SandboxError("Repository paths must be unique.")
        for path in [*self.paths, self.wiki_path]:
            if (
                not path.startswith("/") or "\\" in path or "%" in path or "?" in path or "#" in path
                or any(part in {"", ".", ".."} or any(ord(char) < 32 for char in part) for part in path[1:].split("/"))
            ):
                raise SandboxError("Explicit absolute paths without traversal or encoded separators are required.")
        return self

    @property
    def repo(self) -> AzureRepository:
        return AzureRepository(self.organization, self.project, self.repository)

    @property
    def wiki_uri(self) -> str:
        prefix = "/".join(quote(part, safe="") for part in (
            self.organization, self.project, "_apis", "wiki", "wikis", self.wiki, "pages",
        ))
        return "https://dev.azure.com/" + prefix + "?" + urlencode({
            "path": self.wiki_path, "versionDescriptor.version": self.wiki_commit,
            "versionDescriptor.versionType": "commit", "api-version": "7.1",
        })


class Capture(StrictModel):
    kind: Literal["azure_devops_get_capture"] = "azure_devops_get_capture"
    captured_at: datetime
    plan_sha256: str
    identity: ReadIdentity
    payload: EvaluationRequest


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def check_identity(token: str, expected: ReadIdentity, *, audience: str = ADO_AUDIENCE) -> None:
    """The SDK acquires the token; claims restrict its use, not authenticate external tokens."""
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        actual = ReadIdentity(
            tenant_id=claims["tid"], object_id=claims["oid"], client_id=claims.get("appid", claims.get("azp")),
        )
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise SandboxError("Cannot establish the dedicated Azure DevOps read identity.") from exc
    if actual != expected or claims.get("aud") != audience or claims.get("scp"):
        raise SandboxError("Token is not the approved application identity and requested audience.")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class AzureDevOpsReader:
    """No generic URL or write method is exposed to the caller or the model."""

    def __init__(self, plan: SandboxPlan, token: str) -> None:
        check_identity(token, plan.read_identity)
        self.plan, self.token = plan, token
        self.allowed = {
            **{
                azure_file_uri(plan.repo, path, plan.commit) + "&api-version=7.1&includeContent=true": "git"
                for path in plan.paths
            },
            plan.wiki_uri + "&includeContent=true": "wiki",
        }
        self.remaining = len(self.allowed)
        self.opener = build_opener(NoRedirect())

    def get(self, uri: str) -> tuple[dict[str, Any], dict[str, str]]:
        if uri not in self.allowed or self.remaining <= 0:
            raise SandboxError("Read exceeds the approved source boundary or request budget.")
        self.remaining -= 1
        request = Request(uri, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise SandboxError("Source response exceeds the capture limit.")
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise SandboxError("Source response must be a JSON object.")
                return payload, {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            # HTTPError retains the request URL and may include upstream response bodies.
            raise SandboxError(f"Azure DevOps GET failed (HTTP {exc.code}); capture stopped.") from None


def source(source_id: str, kind: Literal["git", "wiki"], uri: str, version: str, content: str) -> SourceSnapshot:
    return SourceSnapshot(
        id=source_id, source=kind, uri=uri, version=version, content=content,
        availability="available", sha256=digest(content),
    )


def capture_sources(
    plan: SandboxPlan, get: Callable[[str], tuple[dict[str, Any], dict[str, str]]],
) -> Capture:
    snapshots = []
    for index, path in enumerate(plan.paths):
        uri = azure_file_uri(plan.repo, path, plan.commit) + "&api-version=7.1"
        item, _ = get(uri + "&includeContent=true")
        content = item.get("content")
        if (
            item.get("path") != path or item.get("commitId") != plan.commit
            or not isinstance(content, str) or item.get("objectId") != blob_id(content)
        ):
            raise SandboxError("Repository response does not match the reviewed path, commit and blob.")
        snapshots.append(source(f"code-{index + 1}", "git", uri, plan.commit, content))
    page, headers = get(plan.wiki_uri + "&includeContent=true")
    content = page.get("content")
    if (
        page.get("path") != plan.wiki_path or headers.get("etag", "").strip('"') != plan.wiki_etag
        or not isinstance(content, str) or blob_id(content) != plan.wiki_etag
    ):
        raise SandboxError("Wiki response does not match the reviewed path, ETag and content blob.")
    snapshots.append(source("wiki", "wiki", plan.wiki_uri, plan.wiki_etag, content))
    if sum(len((item.content or "").encode()) for item in snapshots) > MAX_SOURCE_BYTES:
        raise SandboxError("Captured sources exceed the bounded assessment input budget.")
    standard = (ROOT / "data/knowledge/documentation-standard.md").read_text(encoding="utf-8")
    request = AgentRequest.model_validate({
        "contract_version": "1.0.0", "request_id": str(uuid4()), "correlation_id": str(uuid4()),
        "trigger": "eval", "requested_by": "sandbox-evaluation",
        "subject": {
            "repo": f"https://dev.azure.com/{plan.organization}/{plan.project}/_git/{plan.repository}",
            "commit_sha": plan.commit, "changed_paths": [path[1:] for path in plan.paths],
        },
        "context": {"wiki_page_paths": [plan.wiki_path]},
        "task": AssessmentTask(question=plan.question, scope=plan.scope).model_dump(),
        "documentation_standard_ref": "https://github.com/wdhm/foundry-agentic-pattern/blob/"
        + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        + "/data/knowledge/documentation-standard.md",
    })
    return Capture(
        captured_at=datetime.now(UTC), plan_sha256=digest(plan.model_dump_json()), identity=plan.read_identity,
        payload=EvaluationRequest(
            interface_version="1.0.0", source_mode="supplied_sources", request=request,
            standard=SuppliedStandard(content=standard, sha256=digest(standard)), sources=snapshots,
        ),
    )


def validate_capture(plan: SandboxPlan, capture: Capture) -> None:
    payload = capture.payload
    if (
        capture.plan_sha256 != digest(plan.model_dump_json()) or capture.identity != plan.read_identity
        or capture.captured_at.tzinfo is None or payload.source_mode != "supplied_sources"
        or payload.request.subject.repo
        != f"https://dev.azure.com/{plan.organization}/{plan.project}/_git/{plan.repository}"
        or payload.request.subject.commit_sha != plan.commit
        or payload.request.task != AssessmentTask(question=plan.question, scope=plan.scope)
        or payload.request.context.wiki_page_paths != [plan.wiki_path]
        or payload.request.subject.changed_paths != [path[1:] for path in plan.paths]
    ):
        raise SandboxError("Capture does not match the reviewed source plan.")
    expected = [
        ("git", azure_file_uri(plan.repo, path, plan.commit) + "&api-version=7.1", plan.commit)
        for path in plan.paths
    ] + [("wiki", plan.wiki_uri, plan.wiki_etag)]
    if [(item.source, item.uri, item.version) for item in payload.sources] != expected or any(
        item.availability != "available" for item in payload.sources
    ):
        raise SandboxError("Capture source boundaries or pins differ from the plan.")
    if any(item.source == "wiki" and blob_id(item.content or "") != plan.wiki_etag for item in payload.sources):
        raise SandboxError("Captured wiki content differs from its pinned Git blob.")
    if sum(len((item.content or "").encode()) for item in payload.sources) > MAX_SOURCE_BYTES:
        raise SandboxError("Captured sources exceed the bounded assessment input budget.")
    standard = (ROOT / "data/knowledge/documentation-standard.md").read_text(encoding="utf-8")
    if payload.standard is None or payload.standard.content != standard:
        raise SandboxError("Capture standard differs from the checked-out documentation standard.")


def prepared_case(plan: SandboxPlan, capture: Capture) -> dict[str, Any]:
    validate_capture(plan, capture)
    return {
        "id": "sandbox-assessment", "mode": "supplied_sources", "scope": plan.scope,
        "request": capture.payload.request.model_copy(update={"request_id": uuid4(), "correlation_id": uuid4()}),
        "sources": [
            item.model_dump(include={"source", "uri", "version", "content"}) for item in capture.payload.sources
        ],
        "rules": capture.payload.standard.content if capture.payload.standard is not None else "",
        "question": plan.question, "expected_status": plan.expected_status,
    }


async def evaluate_capture(
    plan: SandboxPlan, capture: Capture, config: "LoopConfig", cloud: "FoundryEvaluation", output: Path,
) -> dict[str, Any]:
    from tools.eval_loop import LiveDemo, safe_failure
    from tools.release import save

    output = restricted_output(output)
    if config.mode != "supplied_sources_only":
        raise SandboxError("Sandbox capture evaluation requires tools-disabled isolated configuration.")
    if (
        config.settings.get("DOCUMENTATION_ADO_PROJECT") != plan.project
        or config.settings.get("DOCUMENTATION_ADO_WIKI") != plan.wiki
    ):
        raise SandboxError("Evaluation domain differs from the approved capture domain.")
    case = prepared_case(plan, capture)
    demo = LiveDemo(config, cloud)
    demo.cases = [case]
    demo.coverage = {
        "mode": "sandbox_captured_sources", "selected_case_ids": [case["id"]],
        "excluded_case_ids": [item["id"] for item in demo.suite["cases"]],
        "tool_call_accuracy": "not_evaluated", "agent_driven_source_retrieval": False,
    }
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    save(output / "manifest.json", {
        "kind": "sandbox_captured_sources", "plan_sha256": capture.plan_sha256,
        "capture_sha256": digest(capture.model_dump_json()), "captured_at": capture.captured_at.isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "config_sha256": digest(config.model_dump_json()), "coverage": demo.coverage,
        "frozen_files": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in ("src", "data/knowledge")
            for path in sorted((ROOT / folder).rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        },
        "limits": {"candidates": 1, "optimizer_calls": 0, "case_timeout_seconds": 180},
    })
    decision: dict[str, Any] = {
        "status": "blocked", "promoted": False, "promotion_eligible": False, "full_suite_passed": False,
        "coverage": demo.coverage,
    }
    save(output / "decision.json", decision)
    try:
        async with asyncio.timeout(1500):
            passed, rank, _ = await demo.evaluate("", output)
    except Exception as exc:
        decision["error"] = safe_failure(exc)
        save(output / "decision.json", decision)
        raise
    decision.update(status="sandbox_passed" if passed else "sandbox_failed", minimum_normalized_score=rank)
    save(output / "decision.json", decision)
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "capture":
            command.add_argument("--capture-approved-readonly", action="store_true")
        else:
            command.add_argument("--capture", type=Path, required=True)
            command.add_argument("--config", type=Path, required=True)
            command.add_argument("--execute-approved-isolated", action="store_true")
    args = parser.parse_args(argv)
    try:
        args.output = restricted_output(args.output)
        plan = SandboxPlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
        if args.command == "capture":
            if not args.capture_approved_readonly or os.environ.get("SANDBOX_READ_APPROVED") != "true":
                raise SandboxError("Explicit read-only source capture approval is required.")
            from azure.identity import AzureCliCredential

            with AzureCliCredential() as credential:
                token = credential.get_token(ADO_AUDIENCE + "/.default").token
                reader = AzureDevOpsReader(plan, token)
                capture = capture_sources(plan, reader.get)
            validate_capture(plan, capture)
            args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                target.write(capture.model_dump_json(indent=2) + "\n")
            print("Source capture complete; no model evaluation or wiki write performed.")
            return 0
        if not args.execute_approved_isolated or os.environ.get("EVAL_LOOP_APPROVED") != "true":
            raise SandboxError("Explicit isolated model execution approval is required.")
        from azure.ai.projects import AIProjectClient
        from azure.identity import AzureCliCredential

        from tools.eval_loop import LoopConfig, runtime_settings
        from tools.release import FoundryEvaluation

        capture = Capture.model_validate_json(args.capture.read_text(encoding="utf-8"))
        validate_capture(plan, capture)
        config = LoopConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        if config.mode != "supplied_sources_only":
            raise SandboxError("Sandbox capture evaluation requires tools-disabled isolated configuration.")
        settings = runtime_settings(config)
        subprocess.run(
            ["git", "diff", "--exit-code", "HEAD", "--", "src", "data/knowledge", "pyproject.toml"],
            cwd=ROOT, check=True, capture_output=True,
        )
        with AzureCliCredential() as credential:
            check_identity(
                credential.get_token("https://ai.azure.com/.default").token,
                plan.read_identity, audience="https://ai.azure.com",
            )
            with (
                AIProjectClient(endpoint=settings.project_endpoint, credential=credential) as project,
                project.get_openai_client(timeout=180, max_retries=0) as client,
            ):
                decision = asyncio.run(
                    evaluate_capture(plan, capture, config, FoundryEvaluation(project, client), args.output),
                )
        print("Sandbox evaluation: " + decision["status"] + "; live tool-call accuracy not evaluated.")
        return 0 if decision["status"] == "sandbox_passed" else 1
    except Exception as exc:
        # Restrict diagnostics: SDK, source and model exceptions may include raw content.
        from tools.eval_loop import safe_failure

        detail = str(exc) if isinstance(exc, SandboxError) else json.dumps(safe_failure(exc), sort_keys=True)
        print(f"Sandbox operation blocked: {detail}; no passing result claimed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
