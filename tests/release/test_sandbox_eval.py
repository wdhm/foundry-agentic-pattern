"""Synthetic transport tests; these do not claim Azure DevOps or model execution."""

import asyncio
import base64
import json
import subprocess
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from tools.eval_loop import LiveDemo, LoopConfig
from tools.release_sources import blob_id
from tools.sandbox_eval import (
    ADO_AUDIENCE,
    MAX_RESPONSE_BYTES,
    AzureDevOpsReader,
    Capture,
    NoRedirect,
    SandboxError,
    SandboxPlan,
    UserIdentity,
    approve_identity,
    capture_sources,
    check_identity,
    evaluate_capture,
    main,
    prepared_case,
    restricted_output,
    validate_capture,
)


@pytest.fixture
def plan():
    return SandboxPlan(
        organization="foundry-agentic", project="integration-team", repository="integration-team",
        commit="a" * 40, paths=["/src/order_sync.py", "/config/settings.json"],
        wiki="integration-team.wiki", wiki_path="/Order Sync/Overview",
        wiki_commit="b" * 40, wiki_etag=blob_id("Sparse documentation.\n"),
        read_identity={"tenant_id": uuid4(), "object_id": uuid4(), "client_id": uuid4()},
        read_approval_reference="TEST ONLY approved reads",
        question="What retry policy is implemented and is it documented?", scope="change_review",
        expected_status="gaps_found", expectation_review_reference="TEST ONLY reviewed expected status",
    )


def token(plan, **updates):
    claims = {
        "aud": ADO_AUDIENCE, "oid": str(plan.read_identity.object_id),
        "tid": str(plan.read_identity.tenant_id),
        "appid": str(getattr(plan.read_identity, "client_id", uuid4())), **updates,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "header." + encoded + ".signature"


@pytest.fixture
def user_plan(plan):
    return SandboxPlan.model_validate({
        **plan.model_dump(),
        "read_identity": {
            "mode": "delegated_user", "tenant_id": "cc48e4fe-6662-414d-aeff-4eb633735b38",
            "object_id": "cbc26d4a-7626-45bc-bd50-c2161c41bd71",
        },
        "model_identity": plan.read_identity.model_dump(),
        "model_identity_review_reference": "TEST ONLY Foundry permissions review",
    })


@pytest.mark.parametrize("updates", [
    {"oid": str(uuid4())}, {"tid": str(uuid4())}, {"aud": "https://management.azure.com/"},
    {"scp": None}, {"scp": ""}, {"scp": " "}, {"scp": ["user_impersonation"]}, {"idtyp": "app"},
])
def test_delegated_claims_rejected(user_plan, updates):
    with pytest.raises(ValueError):
        check_identity(token(user_plan, **{"scp": "user_impersonation", **updates}), user_plan.read_identity)


def test_delegated_user_is_object_not_cli_client(user_plan):
    assert isinstance(user_plan.read_identity, UserIdentity)
    for client in (uuid4(), uuid4()):
        check_identity(token(user_plan, scp="user_impersonation", appid=str(client)), user_plan.read_identity)
    check_identity(
        token(user_plan, scp="user_impersonation", aud="https://ai.azure.com"),
        user_plan.read_identity, audience="https://ai.azure.com",
    )
    with pytest.raises(ValueError):
        check_identity(token(user_plan, scp="user_impersonation"), user_plan.read_identity, audience="https://ai.azure.com")


@pytest.mark.parametrize("variable", ["CI", "GITHUB_ACTIONS", "TF_BUILD", "BUILD_BUILDID"])
def test_delegated_ci_rejected(user_plan, monkeypatch, variable):
    monkeypatch.setenv("SANDBOX_MANUAL_USER_APPROVED", "true")
    monkeypatch.setenv(variable, "true")
    with pytest.raises(ValueError, match="forbidden in CI"):
        AzureDevOpsReader(user_plan, token(user_plan, scp="user_impersonation"), manual_user_approved=True)


def test_manual_approval_and_app_default(plan, user_plan, monkeypatch):
    for variable in ("CI", "GITHUB_ACTIONS", "TF_BUILD", "BUILD_BUILDID"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("SANDBOX_MANUAL_USER_APPROVED", raising=False)
    approve_identity(plan.read_identity, False)
    with pytest.raises(ValueError, match="manual delegated-user approval"):
        approve_identity(user_plan.read_identity, True)
    monkeypatch.setenv("SANDBOX_MANUAL_USER_APPROVED", "true")
    with pytest.raises(ValueError, match="manual delegated-user approval"):
        approve_identity(user_plan.read_identity, False)
    AzureDevOpsReader(user_plan, token(user_plan, scp="user_impersonation"), manual_user_approved=True)


def test_cli_user_ci_rejected_before_credentials(user_plan, tmp_path, monkeypatch, capsys):
    import azure.identity

    def forbidden(*args, **kwargs):
        pytest.fail("Credentials must not be acquired in CI user mode")

    monkeypatch.setattr(azure.identity, "AzureCliCredential", forbidden)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SANDBOX_READ_APPROVED", "true")
    monkeypatch.setenv("SANDBOX_MANUAL_USER_APPROVED", "true")
    path = tmp_path / "plan.json"
    path.write_text(user_plan.model_dump_json())
    output = tmp_path / "capture.json"
    assert main([
        "capture", "--plan", str(path), "--output", str(output),
        "--capture-approved-readonly", "--manual-user-approved",
    ]) == 1
    assert "forbidden in CI" in capsys.readouterr().err
    assert not output.exists()


def test_user_capture_replay_preserves_separate_identity(user_plan, plan):
    get, _ = transport(user_plan)
    capture = Capture.model_validate_json(capture_sources(user_plan, get).model_dump_json())
    validate_capture(user_plan, capture)
    assert capture.identity == user_plan.read_identity
    assert user_plan.model_identity == plan.read_identity
    with pytest.raises(ValueError, match="reviewed model identity"):
        SandboxPlan.model_validate({**user_plan.model_dump(), "model_identity": None})
    with pytest.raises(ValueError, match="permissions review"):
        SandboxPlan.model_validate({**user_plan.model_dump(), "model_identity_review_reference": None})
    with pytest.raises(ValueError, match="does not match"):
        validate_capture(plan, capture)


def test_evaluate_cli_preflights_model_not_source_identity(user_plan, plan, tmp_path, monkeypatch, capsys):
    import azure.ai.projects
    import azure.identity

    import tools.sandbox_eval as sandbox

    calls = []

    class Credential:
        def __init__(self, *, tenant_id):
            assert tenant_id == str(plan.read_identity.tenant_id)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_token(self, scope):
            calls.append(scope)
            return SimpleNamespace(token=token(plan, aud="https://ai.azure.com"))

    def project(**kwargs):
        raise SandboxError("TEST STOP after successful model preflight")

    run = sandbox.subprocess.run

    def clean_diff(command, **kwargs):
        if command[:3] == ["git", "diff", "--exit-code"]:
            return SimpleNamespace(returncode=0)
        return run(command, **kwargs)

    monkeypatch.setattr(azure.identity, "AzureCliCredential", Credential)
    monkeypatch.setattr(azure.ai.projects, "AIProjectClient", project)
    monkeypatch.setattr(sandbox.subprocess, "run", clean_diff)
    monkeypatch.setenv("EVAL_LOOP_APPROVED", "true")
    # App-only evaluation of previously captured user sources needs no user login/approval.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    get, _ = transport(user_plan)
    paths = [tmp_path / name for name in ("plan.json", "capture.json", "config.json")]
    for path, model in zip(paths, (user_plan, capture_sources(user_plan, get), config(user_plan)), strict=True):
        path.write_text(model.model_dump_json())
    assert main([
        "evaluate", "--plan", str(paths[0]), "--capture", str(paths[1]),
        "--config", str(paths[2]), "--output", str(tmp_path / "run"), "--execute-approved-isolated",
    ]) == 1
    assert calls == ["https://ai.azure.com/.default"]
    assert "TEST STOP after successful model preflight" in capsys.readouterr().err


def transport(plan):
    calls = []

    def get(uri):
        calls.append(uri)
        if "/_apis/git/" in uri:
            path = plan.paths[len(calls) - 1]
            text = "maxAttempts = 5\n"
            return {"path": path, "commitId": plan.commit, "objectId": blob_id(text), "content": text}, {}
        return {"path": plan.wiki_path, "content": "Sparse documentation.\n"}, {"etag": '"' + plan.wiki_etag + '"'}

    return get, calls


def config(plan):
    return LoopConfig(
        mode="supplied_sources_only",
        settings={
            "DOCUMENTATION_PROJECT_ENDPOINT": "https://isolated.services.ai.azure.com/api/projects/evaluation",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "candidate", "DOCUMENTATION_MODEL_VERSION": "2026-03-05",
            "DOCUMENTATION_ADO_PROJECT": plan.project, "DOCUMENTATION_ADO_WIKI": plan.wiki,
            "DOCUMENTATION_AUTH_MODE": "azure_cli",
        },
        observed_model="gpt-5.4-2026-03-05", evaluator_deployment="judge", evaluator_version="2026-03-17",
        optimizer_deployment="optimizer", optimizer_version="2026-03-17",
        isolation_review_reference="TEST ONLY isolated config",
        serving_project_endpoint="https://serving.services.ai.azure.com/api/projects/production",
    )


def test_capture_exact_pins_contract_and_no_gold_input(plan):
    get, calls = transport(plan)
    capture = capture_sources(plan, get)
    validate_capture(plan, capture)
    assert len(calls) == len(plan.paths) + 1
    assert all("versionDescriptor.version=" in uri and "includeContent=true" in uri for uri in calls)
    assert capture.payload.source_mode == "supplied_sources"
    assert capture.payload.request.subject.repo.endswith("/_git/integration-team")
    assert all(source.sha256 for source in capture.payload.sources)
    assert plan.expected_status not in capture.payload.model_dump_json()
    assert plan.expectation_review_reference not in capture.payload.model_dump_json()
    case = prepared_case(plan, capture)
    assert case["scope"] == plan.scope and case["expected_status"] == plan.expected_status
    assert case["request"].request_id != capture.payload.request.request_id


@pytest.mark.parametrize("field,value", [
    ("paths", ["/../secret"]), ("paths", ["/src/a", "/src/a"]), ("paths", ["/src/%2e%2e/secret"]),
    ("paths", ["/src\\secret"]), ("paths", ["/src/a?x=1"]), ("wiki_path", "/../page"),
    ("organization", "other/org"), ("commit", "main"), ("paths", ["/a"] * 6),
])
def test_reject_ambiguous_or_unbounded_plans(plan, field, value):
    with pytest.raises(ValueError):
        SandboxPlan.model_validate({**plan.model_dump(), field: value})


@pytest.mark.parametrize("claims", [
    {"oid": str(uuid4())}, {"tid": str(uuid4())}, {"appid": str(uuid4())},
    {"aud": "https://management.azure.com/"}, {"scp": "user_impersonation"},
])
def test_wrong_or_delegated_identity_rejected_before_io(plan, claims):
    with pytest.raises(ValueError, match="approved application identity"):
        AzureDevOpsReader(plan, token(plan, **claims))


def test_malformed_identity_rejected(plan):
    with pytest.raises(ValueError, match="Cannot establish"):
        check_identity("not-a-token", plan.read_identity)
    check_identity(token(plan), plan.read_identity)


@pytest.mark.parametrize("field,value", [
    ("commitId", "c" * 40), ("objectId", "c" * 40), ("path", "/other.py"), ("content", None),
])
def test_repository_drift_stops_capture(plan, field, value):
    get, calls = transport(plan)

    def drift(uri):
        item, headers = get(uri)
        item[field] = value
        return item, headers

    with pytest.raises(ValueError, match="Repository response"):
        capture_sources(plan, drift)
    assert len(calls) == 1


@pytest.mark.parametrize("bad_etag,bad_content", [(True, False), (False, True)])
def test_wiki_drift_stops_capture(plan, bad_etag, bad_content):
    get, _ = transport(plan)

    def drift(uri):
        item, headers = get(uri)
        if "/_apis/wiki/" in uri:
            if bad_etag:
                headers["etag"] = "c" * 40
            if bad_content:
                item["content"] = "changed"
        return item, headers

    with pytest.raises(ValueError, match="Wiki response"):
        capture_sources(plan, drift)


def test_source_budget_exact_boundary(plan):
    plan = plan.model_copy(update={"paths": ["/src/order_sync.py"]})

    def get(uri):
        if "/_apis/git/" in uri:
            content = "x" * (80_000 - len("Sparse documentation.\n"))
            return {
                "path": plan.paths[0], "commitId": plan.commit, "objectId": blob_id(content), "content": content,
            }, {}
        return {"path": plan.wiki_path, "content": "Sparse documentation.\n"}, {"etag": plan.wiki_etag}

    validate_capture(plan, capture_sources(plan, get))

    def oversized(uri):
        item, headers = get(uri)
        if "/_apis/git/" in uri:
            item["content"] += "x"
            item["objectId"] = blob_id(item["content"])
        return item, headers

    with pytest.raises(ValueError, match="input budget"):
        capture_sources(plan, oversized)


def test_reader_does_not_redirect_or_read_outside_allowlist(plan):
    reader = AzureDevOpsReader(plan, token(plan))
    with pytest.raises(ValueError, match="boundary"):
        reader.get("https://example.com/secret")
    assert reader.remaining == 3
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com") is None


def test_reader_http_failure_redacts_body_and_url(plan):
    reader = AzureDevOpsReader(plan, token(plan))
    reader.opener = SimpleNamespace(open=lambda *args, **kwargs: (_ for _ in ()).throw(
        HTTPError("https://secret.example", 401, "PRIVATE TEXT", {}, BytesIO(b"PRIVATE BODY")),
    ))
    with pytest.raises(ValueError, match="HTTP 401") as error:
        reader.get(next(iter(reader.allowed)))
    assert "PRIVATE" not in str(error.value) and "secret.example" not in str(error.value)


def test_reader_limits_response_and_request_budget(plan):
    reader = AzureDevOpsReader(plan, token(plan))
    response = BytesIO(b"x" * (MAX_RESPONSE_BYTES + 1))
    reader.opener = SimpleNamespace(open=lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="response exceeds"):
        reader.get(next(iter(reader.allowed)))
    reader.remaining = 0
    with pytest.raises(ValueError, match="request budget"):
        reader.get(next(iter(reader.allowed)))


def test_replay_rejects_modified_plan_capture_and_standard(plan):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    with pytest.raises(ValueError, match="reviewed source plan"):
        validate_capture(plan.model_copy(update={"commit": "d" * 40}), capture)
    raw = json.loads(capture.model_dump_json())
    raw["payload"]["sources"][0]["content"] = "tampered"
    with pytest.raises(ValueError):
        Capture.model_validate(raw)
    changed = deepcopy(capture)
    changed.payload.standard = None
    with pytest.raises(ValueError, match="standard"):
        validate_capture(plan, changed)


@pytest.mark.parametrize("identity_mode", ["application", "delegated_user"])
@pytest.mark.parametrize("passed", [True, False])
def test_reuses_existing_runner_once_no_optimizer_or_live_tool_claim(
    plan, user_plan, tmp_path, monkeypatch, passed, identity_mode,
):
    if identity_mode == "delegated_user":
        plan = user_plan
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    invocations = []

    async def evaluate(demo, candidate, output):
        assert candidate == "" and demo.cases[0]["id"] == "sandbox-assessment"
        assert demo.cases[0]["mode"] == "supplied_sources"
        invocations.append(demo)
        return passed, 1.0, {}

    monkeypatch.setattr(LiveDemo, "evaluate", evaluate)
    output = tmp_path / "run"
    result = asyncio.run(evaluate_capture(plan, capture, config(plan), object(), output))
    assert len(invocations) == 1
    assert result["status"] == ("sandbox_passed" if passed else "sandbox_failed")
    assert result["full_suite_passed"] is False and result["promoted"] is False
    assert result["coverage"]["tool_call_accuracy"] == "not_evaluated"
    assert result["coverage"]["agent_driven_source_retrieval"] is False
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["limits"]["optimizer_calls"] == 0
    assert manifest["source_identity"] == plan.read_identity.model_dump(mode="json")
    assert manifest["model_identity"] == (plan.model_identity or plan.read_identity).model_dump(mode="json")
    assert manifest["model_identity_review_reference"] == plan.model_identity_review_reference
    with pytest.raises(ValueError, match="already exists"):
        asyncio.run(evaluate_capture(plan, capture, config(plan), object(), output))


def test_serving_target_is_rejected_without_model_calls(plan, tmp_path):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    settings = config(plan)
    settings.serving_project_endpoint = settings.settings["DOCUMENTATION_PROJECT_ENDPOINT"]
    with pytest.raises(ValueError):
        asyncio.run(evaluate_capture(plan, capture, settings, object(), tmp_path / "run"))
    assert not (tmp_path / "run").exists()


def test_operational_failure_keeps_blocked_redacted_decision(plan, tmp_path, monkeypatch):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)

    async def fail(*args):
        raise RuntimeError("PRIVATE SOURCE AND MODEL BODY")

    monkeypatch.setattr(LiveDemo, "evaluate", fail)
    output = tmp_path / "run"
    with pytest.raises(RuntimeError):
        asyncio.run(evaluate_capture(plan, capture, config(plan), object(), output))
    decision = json.loads((output / "decision.json").read_text())
    assert decision["status"] == "blocked" and decision["full_suite_passed"] is False
    assert decision["error"] == {"exception": "RuntimeError"}
    assert "PRIVATE" not in (output / "decision.json").read_text()


@pytest.mark.parametrize("change", ["mode", "domain"])
def test_wrong_evaluation_configuration_is_rejected_before_cloud(plan, tmp_path, change):
    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    settings = config(plan)
    if change == "mode":
        settings.mode = "full_suite"
    else:
        settings.settings["DOCUMENTATION_ADO_PROJECT"] = "other-project"
    with pytest.raises(ValueError):
        asyncio.run(evaluate_capture(plan, capture, settings, object(), tmp_path / "run"))
    assert not (tmp_path / "run").exists()


def test_cli_read_approval_is_required_before_credentials(plan, tmp_path, capsys):
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json())
    output = tmp_path / "capture.json"
    assert main(["capture", "--plan", str(path), "--output", str(output)]) == 1
    assert "approval is required" in capsys.readouterr().err
    assert not output.exists()


@pytest.fixture
def output_repo(tmp_path, monkeypatch):
    import tools.sandbox_eval as sandbox

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    (root / ".gitignore").write_text("evals/results/\n")
    monkeypatch.setattr(sandbox, "ROOT", root)
    return root


@pytest.mark.parametrize("command", ["capture", "evaluate"])
@pytest.mark.parametrize("location", ["src/leak.json", "evals/capture.json", ".git/leak.json", "new-output"])
def test_cli_rejects_repo_output_before_reading_inputs_or_credentials(output_repo, command, location, capsys):
    output = output_repo / location
    arguments = [command, "--plan", "nonexistent.json", "--output", str(output)]
    if command == "evaluate":
        arguments += ["--capture", "nonexistent.json", "--config", "nonexistent.json"]
    assert main(arguments) == 1
    assert "Repository output must" in capsys.readouterr().err
    assert not output.exists()


def test_only_ignored_untracked_repo_results_allowed(output_repo):
    output = output_repo / "evals/results/run"
    assert restricted_output(output) == output
    assert not output.exists()
    (output_repo / ".gitignore").write_text("")
    with pytest.raises(ValueError, match="must be ignored"):
        restricted_output(output)
    assert not output.exists()


def test_existing_cache_directory_retains_full_tracked_path_guard(output_repo):
    from tools.precision_recall.__main__ import cache_directory

    cache = output_repo / "evals/results/cache"
    assert cache_directory(cache) == cache
    assert cache_directory(cache) == cache
    tracked = cache / "tracked.json"
    tracked.write_text("test-only")
    subprocess.run(["git", "add", "--force", str(tracked)], cwd=output_repo, check=True)
    with pytest.raises(ValueError, match="no tracked paths"):
        cache_directory(cache)
    with pytest.raises(ValueError, match="Repository output must"):
        cache_directory(output_repo / "src")


def test_tracked_results_are_rejected_even_when_deleted(output_repo):
    tracked = output_repo / "evals/results/capture.json"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("test-only")
    subprocess.run(["git", "add", "--force", str(tracked)], cwd=output_repo, check=True)
    tracked.unlink()
    with pytest.raises(ValueError, match="no tracked paths"):
        restricted_output(tracked)
    assert not tracked.exists()


def test_external_output_preserved_and_symlink_to_repo_blocked(output_repo, tmp_path):
    external = tmp_path / "private/capture.json"
    assert restricted_output(external) == external
    link = tmp_path / "linked-repo"
    link.symlink_to(output_repo, target_is_directory=True)
    with pytest.raises(ValueError, match="Repository output must"):
        restricted_output(link / "src/leak.json")
    assert not (output_repo / "src").exists()


def test_nested_invocation_cannot_treat_repo_parent_as_external(output_repo, monkeypatch):
    import tools.sandbox_eval as sandbox

    nested = output_repo / "nested"
    nested.mkdir()
    monkeypatch.setattr(sandbox, "ROOT", nested)
    with pytest.raises(ValueError, match="repository root"):
        restricted_output(output_repo / "leak.json")
    assert not (output_repo / "leak.json").exists()


def test_rehashed_git_capture_is_not_a_signed_source_attestation(plan):
    from tools.sandbox_eval import digest

    get, _ = transport(plan)
    capture = capture_sources(plan, get)
    raw = json.loads(capture.model_dump_json())
    raw["payload"]["sources"][0]["content"] = "locally rewritten content"
    with pytest.raises(ValueError, match="SHA-256"):
        Capture.model_validate(raw)
    raw["payload"]["sources"][0]["sha256"] = digest(raw["payload"]["sources"][0]["content"])
    validate_capture(plan, Capture.model_validate(raw))
