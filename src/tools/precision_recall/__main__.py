"""Read-only pinned ADO evaluation. No agent replay, wiki writes or implicit paid runs."""

import argparse
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from contracts.repositories import azure_repository
from tools.ado_transport import JsonGet
from tools.sandbox_eval import (
    ADO_AUDIENCE,
    SandboxError,
    approve_identity,
    check_identity,
    restricted_output,
)

from . import calibration
from .llm import JsonLLM
from .models import Config, IdentityFile, Manifest
from .pipeline import run
from .sources import Reader, api, private_json, safe_value, validate_capture


def approval(flag: bool, variable: str) -> None:
    if not flag or os.environ.get(variable) != "true":
        raise SandboxError("Missing explicit approval: " + variable)


def cache_directory(path: Path) -> Path:
    path = restricted_output(path, allow_existing_directory=True)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    return path


@contextmanager
def cloud(config: Config, manual_user_approved: bool) -> Any:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import ModelDeployment
    from azure.identity import AzureCliCredential

    approve_identity(config.model_identity, manual_user_approved)
    with AzureCliCredential(tenant_id=str(config.model_identity.tenant_id)) as credential:
        check_identity(
            credential.get_token("https://ai.azure.com/.default").token,
            config.model_identity, audience="https://ai.azure.com",
        )
        with (
            AIProjectClient(endpoint=config.project_endpoint, credential=credential) as project,
            project.get_openai_client(timeout=config.timeout_seconds, max_retries=0) as client,
        ):
            for expected in (config.candidate, config.extractor, config.verifier):
                actual = project.deployments.get(expected.deployment)
                if (
                    not isinstance(actual, ModelDeployment)
                    or actual.model_name != expected.model or actual.model_version != expected.version
                ):
                    raise SandboxError("Foundry deployment metadata differs from approved model/version.")
            yield project, client
            for expected in (config.candidate, config.extractor, config.verifier):
                actual = project.deployments.get(expected.deployment)
                if (
                    not isinstance(actual, ModelDeployment)
                    or actual.model_name != expected.model or actual.model_version != expected.version
                ):
                    raise SandboxError("Foundry deployment changed during execution; result requires review.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("preflight", "capture", "run", "publish", "export", "calibrate", "coverage-review"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--output", type=Path, required=name != "preflight")
        command.add_argument("--manual-user-approved", action="store_true")
        if name in {"capture", "run"}:
            command.add_argument("--cache", type=Path, required=True)
        if name in {"run", "export"}:
            command.add_argument("--capture", type=Path, required=True)
        if name in {"publish", "export", "calibrate"}:
            command.add_argument("--run", type=Path, required=True)
        if name == "capture":
            command.add_argument("--capture-approved-readonly", action="store_true")
        if name == "run":
            command.add_argument("--execute-approved-isolated", action="store_true")
        if name == "publish":
            command.add_argument("--publish-approved-sanitized", action="store_true")
            command.add_argument("--run-id", required=True)
        if name == "calibrate":
            command.add_argument("--reviewer-a", type=Path, required=True)
            command.add_argument("--reviewer-b", type=Path, required=True)
        if name == "coverage-review":
            command.add_argument("--adjudications", type=Path, required=True)
    pin = commands.add_parser("resolve-pin")
    pin.add_argument("--identity", type=Path, required=True)
    pin.add_argument("--repository", required=True)
    pin.add_argument("--ref", required=True)
    pin.add_argument("--output", type=Path, required=True)
    pin.add_argument("--manual-user-approved", action="store_true")
    pin.add_argument("--capture-approved-readonly", action="store_true")
    return result


def resolve_pin(args: argparse.Namespace) -> None:
    from azure.identity import AzureCliCredential

    approval(args.capture_approved_readonly, "SANDBOX_READ_APPROVED")
    identity = IdentityFile.model_validate_json(args.identity.read_text(encoding="utf-8")).read_identity
    approve_identity(identity, args.manual_user_approved)
    repo = azure_repository(args.repository)
    if not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", args.ref) or ".." in args.ref:
        raise SandboxError("An exact refs/heads/... metadata reference is required.")
    uri = api(repo, "refs", {"filter": args.ref.removeprefix("refs/")})
    with AzureCliCredential(tenant_id=str(identity.tenant_id)) as credential:
        token = credential.get_token(ADO_AUDIENCE + "/.default").token
        check_identity(token, identity)
        payload, _ = JsonGet(token, {uri}, 1).get(uri)
    matches = [r for r in payload["value"] if r["name"] == args.ref]
    if len(matches) != 1 or not re.fullmatch("[0-9a-f]{40}", matches[0]["objectId"]):
        raise SandboxError("Cannot resolve exactly one authorized commit pin.")
    private_json(args.output, {
        "repository": args.repository, "resolved_ref": args.ref, "commit": matches[0]["objectId"],
        "identity": identity.model_dump(mode="json"),
        "scope": "Ref metadata only; no source content read at branch tip. Review and freeze in manifest.",
    })


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    output_approved = False
    try:
        if args.output is not None:
            args.output = restricted_output(args.output)
            output_approved = True
        if args.command == "resolve-pin":
            resolve_pin(args)
        else:
            manifest = Manifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
            config = Config.model_validate_json(args.config.read_text(encoding="utf-8"))
            safe_value(manifest.model_dump(mode="json"))
            safe_value(config.model_dump(mode="json"))
            if args.command == "preflight":
                print("Local configuration valid; ADO/Foundry access, pins, "
                      "calibration and live readiness not checked.")
                return 0
            assert args.output is not None
            if args.command == "capture":
                approval(args.capture_approved_readonly, "SANDBOX_READ_APPROVED")
                approve_identity(manifest.read_identity, args.manual_user_approved)
                from azure.identity import AzureCliCredential

                with AzureCliCredential(tenant_id=str(manifest.read_identity.tenant_id)) as credential:
                    reader = Reader.authenticated(
                        manifest, config, cache_directory(args.cache),
                        credential.get_token(ADO_AUDIENCE + "/.default").token,
                        manual_user_approved=args.manual_user_approved,
                    )
                    private_json(args.output, reader.capture())
            elif args.command in {"run", "export"}:
                capture = json.loads(args.capture.read_text(encoding="utf-8"))
                validate_capture(capture, manifest)
                if args.command == "export":
                    calibration.export(args.run, capture, args.output)
                else:
                    approval(args.execute_approved_isolated, "EVAL_LOOP_APPROVED")
                    subprocess.run(
                        ["git", "diff", "--exit-code", "HEAD", "--", "src", "pyproject.toml"],
                        check=True, capture_output=True,
                    )
                    untracked = subprocess.run(
                        ["git", "ls-files", "--others", "--exclude-standard", "--", "src", "pyproject.toml"],
                        check=True, capture_output=True,
                    )
                    if untracked.stdout:
                        raise SandboxError("Commit pipeline source before paid execution.")
                    with cloud(config, args.manual_user_approved) as (_, client):
                        summary = run(
                            capture, config, JsonLLM(config, client.responses.create),
                            args.output, cache_directory(args.cache),
                        )
                    if not summary["overall"]["complete"]:
                        print("Paired outputs recorded; incomplete/review required, no semantic gate.", file=sys.stderr)
                        return 1
            elif args.command == "publish":
                approval(args.publish_approved_sanitized, "PRECISION_RECALL_PUBLICATION_APPROVED")
                if not re.fullmatch(r"[a-z0-9-]{1,40}", args.run_id):
                    raise SandboxError("A short lowercase publication run ID is required.")
                from .foundry import publish

                summary = json.loads((args.run / "precision_recall_summary.json").read_text(encoding="utf-8"))
                if (args.run / "operation_error.json").exists() or not summary["overall"]["complete"]:
                    raise SandboxError("Incomplete or operationally failed results cannot be published.")
                with cloud(config, args.manual_user_approved) as (project, client):
                    publish(project, client, args.run, args.output, args.run_id, config.verifier.deployment)
            elif args.command == "calibrate":
                private_json(args.output, calibration.score(args.run, args.reviewer_a, args.reviewer_b))
            elif args.command == "coverage-review":
                private_json(args.output, calibration.coverage_review(
                    json.loads(args.adjudications.read_text(encoding="utf-8")),
                ))
        print("Operation completed; no wiki/repository write, agent replay, promotion or calibrated gate claimed.")
        return 0
    except Exception as exc:
        # Source/model/SDK exceptions can contain content and tokens; only classify them here.
        if output_approved:
            diagnostic = args.output / "operation_error.json" if args.output.is_dir() else args.output
            if not diagnostic.exists():
                private_json(diagnostic, {
                    "status": "blocked", "stage": args.command, "exception": type(exc).__name__,
                    "diagnostic": str(exc) if isinstance(exc, SandboxError) else None,
                    "semantic_gates_enabled": False, "promoted": False,
                })
        print("Operation blocked at " + args.command + "; inspect restricted provenance, no passing result.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
