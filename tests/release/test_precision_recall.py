"""UNIT TESTS ONLY. Synthetic API/model doubles are not demo results or human calibration."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from tools.precision_recall import calibration
from tools.precision_recall.__main__ import main
from tools.precision_recall.foundry import CODE, projection, publish
from tools.precision_recall.llm import JsonLLM, StageError
from tools.precision_recall.models import Claim, Claims, Config, Manifest, Quote
from tools.precision_recall.pipeline import canonicalize, fraction, metrics, run, sections, select
from tools.precision_recall.retrieval import citations_ok, retrieve
from tools.precision_recall.sources import Reader, private_json, redact, safe_text, validate_capture
from tools.release_sources import blob_id

APP = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "object_id": "22222222-2222-2222-2222-222222222222",
    "client_id": "33333333-3333-3333-3333-333333333333",
}


@pytest.fixture
def config():
    return Config(
        schema_version="1", project_endpoint="https://test.services.ai.azure.com/api/projects/eval",
        serving_project_endpoint="https://test.services.ai.azure.com/api/projects/serving",
        model_identity=APP, isolation_review_reference="UNIT TEST", source_exposure_approval_reference="UNIT TEST",
        candidate={"deployment": "candidate", "model": "large", "version": "2026-01-01"},
        extractor={"deployment": "judge", "model": "mini", "version": "2026-02-01"},
        verifier={"deployment": "judge", "model": "mini", "version": "2026-02-01"},
    )


@pytest.fixture
def manifest():
    code = {
        "id": "integration", "organization": "unit-test", "project": "team",
        "repository": "code", "commit": "a" * 40,
    }
    return Manifest.model_validate({
        "schema_version": "1", "read_identity": APP, "read_approval_reference": "UNIT TEST",
        "cases": [{
            "id": "case1", "integration_repo": code, "merge_commit": "a" * 40, "base_commit": "b" * 40,
            "related_repos": [{**code, "id": "infra", "repository": "infra", "commit": "c" * 40}],
            "page": {
                "repo": {**code, "id": "wiki", "repository": "wiki", "commit": "d" * 40},
                "path": "/OrderSync/Overview.md", "origin": "existing_wiki_page",
                "provenance_reference": "UNIT TEST existing page, not agent output",
            },
            "critical_facts": [{
                "fact_id": "f1", "fact": "OrderSync runs every 30 minutes", "severity": "critical",
                "category": "schedule",
                "source": {"file": "integration@" + "a" * 40 + ":/src/OrderSync.cs", "line": 1,
                           "text": '[TimerTrigger("0 */30 * * * *")]'},
            }],
            "facts_author": "UNIT TEST fixture author", "facts_review_reference": "UNIT TEST ONLY",
        }],
    })


def transport(manifest):
    case = manifest.cases[0]
    contents = {
        "code": {"/src/OrderSync.cs": '[TimerTrigger("0 */30 * * * *")]\nvoid Run() {}\n',
                 **{f"/src/other{i}.cs": "class Other {}\n" for i in range(6)}},
        "infra": {"/appsettings.json": '{"ORDERSYNC_BATCH_SIZE": 100}\n'},
        "wiki": {case.page.path: "# OrderSync\nOrderSync runs every 30 minutes.\n"},
    }
    calls = []

    def get(uri):
        calls.append(uri)
        url, query = urlsplit(uri), parse_qs(urlsplit(uri).query)
        repo = url.path.split("/repositories/")[1].split("/")[0]
        if "/diffs/commits" in url.path:
            assert query["baseVersion"] == [case.base_commit] and query["targetVersion"] == [case.merge_commit]
            return {"allChangesIncluded": True, "changes": [
                {"item": {"path": "/src/OrderSync.cs"}, "changeType": "edit"},
            ]}, {}
        pin = query["versionDescriptor.version"][0]
        assert query["versionDescriptor.versionType"] == ["commit"]
        if "recursionLevel" in query:
            value = [
                {"path": path, "commitId": pin, "gitObjectType": "blob", "contentMetadata": {"isBinary": False}}
                for path in contents[repo]
            ]
            return {"count": len(value), "value": value}, {}
        path = query["path"][0]
        text = contents[repo][path]
        if pin == case.base_commit:
            text = text.replace("*/30", "*/15")
        return {"path": path, "content": text, "commitId": pin, "objectId": blob_id(text)}, {}

    return get, calls, contents


def capture(manifest, config, tmp_path):
    get, calls, _ = transport(manifest)
    return Reader(manifest, config, tmp_path / "sources", get, set()).capture(), calls


def response(text, model="mini-2026-02-01"):
    return SimpleNamespace(
        output_text=text, id="resp-unit-test", model=model, status="completed",
        usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 12, "output_tokens": 10, "total_tokens": 22}),
    )


def sender(**kwargs):
    payload = json.loads(kwargs["input"])
    if "section" in payload:
        value = {"claims": [{
            "claim_id": "ignored", "claim": payload["text"], "source_sentence": payload["text"],
            "section": payload["section"], "severity": "normal", "category": "schedule",
        }]}
    elif "evidence" in payload:
        name = payload["evidence"].splitlines()[0].removeprefix("=== ").split(" (lines")[0]
        value = {"verdict": "SUPPORTED", "evidence_quotes": [
            {"file": name, "line": 1, "text": '[TimerTrigger("0 */30 * * * *")]'},
        ], "reason": "The timer matches."}
    else:
        value = {"verdict": "STATED", "page_quote": "OrderSync runs every 30 minutes.", "reason": "Stated exactly."}
    return response(json.dumps(value))


def test_complete_discovery_more_than_five_files_and_immutable_cache(manifest, config, tmp_path):
    data, calls = capture(manifest, config, tmp_path)
    validate_capture(data, manifest)
    assert len(data["cases"][0]["files"]) == 8
    assert "*/15" in data["cases"][0]["diff"] and "*/30" in data["cases"][0]["diff"]
    assert data["cases"][0]["case"]["page"]["origin"] == "existing_wiki_page"
    assert all("/_apis/git/" in uri for uri in calls)
    first_calls = len(calls)
    get, _, _ = transport(manifest)
    again = Reader(manifest, config, tmp_path / "sources", get, set()).capture()
    assert data == again and len(calls) == first_calls
    assert data["read_identity"]["mode"] == "application"
    assert len(list((tmp_path / "sources").glob("*.json"))) > 8


@pytest.mark.parametrize("kind", ["commit", "blob", "truncated_tree", "truncated_diff", "budget", "submodule"])
def test_source_incompleteness_never_silently_samples(manifest, config, tmp_path, kind):
    get, _, _ = transport(manifest)
    if kind == "budget":
        config.max_files = 5

    def bad(uri):
        value, headers = get(uri)
        if kind == "truncated_tree":
            headers["x-ms-continuationtoken"] = "more"
        elif kind == "truncated_diff" and "changes" in value:
            value["allChangesIncluded"] = False
        elif "value" in value:
            if kind == "commit":
                value["value"][0]["commitId"] = "e" * 40
            elif kind == "submodule":
                value["value"][0]["gitObjectType"] = "commit"
        elif "content" in value and kind == "blob":
            value["objectId"] = "e" * 40
        return value, headers

    with pytest.raises(ValueError):
        Reader(manifest, config, tmp_path / "sources", bad, set()).capture()


def test_cache_tamper_and_capture_tamper_rejected(manifest, config, tmp_path):
    data, _ = capture(manifest, config, tmp_path)
    data["cases"][0]["page"] = "changed"
    with pytest.raises(ValueError, match="integrity"):
        validate_capture(data, manifest)
    path = next((tmp_path / "sources").glob("*.json"))
    value = json.loads(path.read_text())
    value["sha256"] = "bad"
    path.write_text(json.dumps(value))
    get, _, _ = transport(manifest)
    with pytest.raises(ValueError, match="integrity"):
        Reader(manifest, config, tmp_path / "sources", get, set()).capture()


def test_related_repo_retrieval_exact_context_and_limit(manifest, config, tmp_path):
    data, _ = capture(manifest, config, tmp_path)
    item = data["cases"][0]
    result = retrieve("`ORDERSYNC_BATCH_SIZE` defaults to 100", "config", item["files"], [], "")
    assert any("infra@" in name for name in result.files)
    assert any('"ORDERSYNC_BATCH_SIZE": 100' in text for text in result.lines.values())
    lines = "\n".join(f"line{i}" for i in range(100))
    result = retrieve("`line50`", "other", {"code": lines}, [], "")
    assert result.lines[("code", 31)] == "line30" and result.lines[("code", 71)] == "line70"
    tiny = retrieve("`line50`", "other", {"code": lines}, [], "", max_bytes=1)
    assert tiny.truncated and not tiny.lines


def test_no_hit_fallback_includes_actual_diff_and_touched_file():
    result = retrieve("unmatched prose", "other", {"file": "code"}, ["file"], "actual diff")
    assert "actual diff" in result.text and result.lines[("file", 1)] == "code"


@pytest.mark.parametrize("file,line,text", [("other", 1, "exact"), ("code", 2, "exact"), ("code", 1, "altered")])
def test_bad_citations_never_accepted(file, line, text):
    evidence = retrieve("`exact`", "other", {"code": "exact"}, [], "")
    assert not citations_ok([Quote(file=file, line=line, text=text)], evidence, allow_empty=False)
    assert citations_ok([Quote(file="code", line=1, text="exact")], evidence, allow_empty=False)
    assert not citations_ok([], evidence, allow_empty=False)
    assert citations_ok([], evidence, allow_empty=True)


def test_secret_redaction_before_disk_and_blocking(tmp_path):
    text = 'API_KEY="sensitive"\npassword: "private"\nurl=https://storage/x?sv=1&sig=supersecret'
    clean = redact(text)
    assert "sensitive" not in clean and "private" not in clean and "supersecret" not in clean
    assert "API_KEY" in clean and "<REDACTED>" in clean
    safe_text(clean)
    private_json(tmp_path / "safe.json", {"content": clean})
    for bad in (text, "-----BEGIN PRIVATE KEY-----", "ghp_" + "X" * 30):
        with pytest.raises(ValueError):
            private_json(tmp_path / "bad.json", {"content": bad})
        assert not (tmp_path / "bad.json").exists()


def test_sanitized_setting_name_is_citable_without_claiming_secret_value():
    line = 'ERP_API_KEY="<REDACTED>"'
    evidence = retrieve("`ERP_API_KEY` is a setting", "config", {"code": line}, [], "")
    assert citations_ok([Quote(file="code", line=1, text=line)], evidence, allow_empty=False)
    assert not citations_ok(
        [Quote(file="code", line=1, text='ERP_API_KEY="invented value"')], evidence, allow_empty=False,
    )


def test_heading_context_fenced_code_and_atomic_handoff():
    page = "# A\none\n## B\ntwo\n```\n# not a heading\n```\n## C\nthree"
    chunks = sections(page)
    assert [name for name, _ in chunks] == ["A", "A > B", "A > C"]
    assert "# not a heading" in chunks[1][1]


def test_seeded_selection_is_canonical_and_every_critical(config):
    claims = [
        Claim(claim_id=f"c{i}", claim=f"Claim {i}", source_sentence=f"Claim {i}", section="S",
              severity="normal", category="other") for i in range(30)
    ] + [Claim(claim_id="critical", claim="Setting name", source_sentence="Setting name", section="S",
               severity="normal", category="config")]
    first = canonicalize(claims)
    second = canonicalize(list(reversed(claims)))
    assert first == second and len(select(first, config)) == 11
    assert [c.claim_id for c in select(first, config)] == [c.claim_id for c in select(second, config)]
    assert sum(c.severity == "critical" for c in select(first, config)) == 1


def test_bounded_json_correction_and_call_provenance(config):
    sent = []

    def send(**kwargs):
        sent.append(kwargs)
        return response("invalid" if len(sent) == 1 else '{"claims":[]}')

    client = JsonLLM(config, send)
    assert client.ask("extract", config.extractor, {"text": "source"}, Claims).claims == []
    assert len(sent) == 2 and "schema" in sent[0]["instructions"]
    assert client.calls[0]["status"] == "invalid_json_or_handoff"
    assert client.calls[1]["tokens"]["total_tokens"] == 22 and client.calls[1]["latency_ms"] >= 0
    client = JsonLLM(config, lambda **kwargs: response("invalid"))
    with pytest.raises(StageError, match="invalid_json"):
        client.ask("extract", config.extractor, {}, Claims)
    assert len(client.calls) == 2


def test_transport_errors_and_known_secrets_are_not_schema_retries(config):
    def fail(**kwargs):
        raise RuntimeError("PRIVATE SOURCE TOKEN")

    client = JsonLLM(config, fail)
    with pytest.raises(StageError, match="transport_error") as error:
        client.ask("extract", config.extractor, {}, Claims)
    assert len(client.calls) == 1 and "PRIVATE" not in str(error.value)
    client = JsonLLM(config, lambda **kwargs: response("-----BEGIN PRIVATE KEY-----"))
    with pytest.raises(StageError, match="secret_detected"):
        client.ask("extract", config.extractor, {}, Claims)
    assert len(client.calls) == 1


def test_paired_pipeline_reuses_versioned_extraction_and_persists_both(manifest, config, tmp_path):
    data, _ = capture(manifest, config, tmp_path)
    first = JsonLLM(config, sender)
    summary = run(data, config, first, tmp_path / "run1", tmp_path / "extractions")
    assert summary["overall"]["precision"]["value"] == 1
    assert summary["overall"]["recall"]["value"] == 1
    assert summary["overall"]["complete"] and summary["semantic_gates_enabled"] is False
    second = JsonLLM(config, sender)
    again = run(data, config, second, tmp_path / "run2", tmp_path / "extractions")
    assert not any(c["stage"] == "extract" for c in second.calls)
    assert again["overall"] == summary["overall"]
    a = json.loads((tmp_path / "run1" / "case1-selection.json").read_text())
    b = json.loads((tmp_path / "run2" / "case1-selection.json").read_text())
    assert a["selected_ids"] == b["selected_ids"]
    assert (tmp_path / "run2" / "precision_results.jsonl").exists()
    assert (tmp_path / "run2" / "recall_results.jsonl").exists()


def test_bad_critical_negative_citation_preserves_safety_failure():
    p = [{"severity": "critical", "status": "completed", "citation_ok": False,
          "verdict": "CONTRADICTED", "effective_verdict": "NOT_VERIFIABLE"}]
    r = [{"severity": "critical", "status": "completed", "citation_ok": False,
          "verdict": "WRONG", "effective_verdict": "MISSING"}]
    value = metrics(p, r, 1, True)
    assert value["precision"]["value"] is None and value["recall"]["value"] == 0
    assert value["safety_status"] == "fail" and not value["complete"]
    assert value["critical_wrong_facts"] == value["critical_contradictions"] == 1
    assert metrics([], [], 0, True)["safety_status"] == "review"
    assert fraction(0, 0)["status"] == "empty_denominator"


def test_failed_extraction_still_records_recall_and_incomplete_summary(manifest, config, tmp_path):
    data, _ = capture(manifest, config, tmp_path)

    def send(**kwargs):
        return response("invalid") if "section" in json.loads(kwargs["input"]) else sender(**kwargs)

    result = run(data, config, JsonLLM(config, send), tmp_path / "run", tmp_path / "extractions")
    assert not result["overall"]["complete"]
    assert result["documents"][0]["extraction_errors"]
    assert len(calibration.rows(tmp_path / "run" / "recall_results.jsonl")) == 1
    assert not list((tmp_path / "extractions").glob("*.json"))


def test_blind_export_and_independent_labels(manifest, config, tmp_path):
    data, _ = capture(manifest, config, tmp_path)
    directory = tmp_path / "run"
    run(data, config, JsonLLM(config, sender), directory, tmp_path / "extractions")
    packet = tmp_path / "blind.csv"
    calibration.export(directory, data, packet)
    with packet.open() as file:
        sheet = list(csv.DictReader(file))
    assert all(not row["label"] and not row["reviewer"] for row in sheet)
    assert all("verdict" not in row["input_json"] and "reason" not in row["input_json"] for row in sheet)
    paths = []
    for reviewer in ("engineer-a", "engineer-b"):
        path = tmp_path / (reviewer + ".csv")
        with path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=calibration.FIELDS)
            writer.writeheader()
            writer.writerows({
                **row, "reviewer": reviewer, "label": {
                    "precision": "SUPPORTED", "recall": "STATED", "extract": "[]",
                }[row["stage"]],
            } for row in sheet)
        paths.append(path)
    result = calibration.score(directory, *paths)
    assert result["stages"]["precision"]["human_vs_human"]["kappa"] is None
    assert result["semantic_gates_enabled"] is False
    with pytest.raises(ValueError, match="Independent"):
        calibration.score(directory, paths[0], paths[0])


def test_agreement_and_human_coverage_targets():
    result = calibration.agreement([("a", "a"), ("a", "b"), ("b", "b"), ("b", "a")], {"a", "b"})
    assert result["agreement"]["value"] == 0.5 and result["kappa"] == 0
    result = calibration.coverage_review([{
        "stage": "retrieval", "origin": "human_adjudication", "review_reference": "unit test",
        "input_sha256": "unit test", "needed_files": ["infra"], "retrieved_files": ["code"],
    }])
    assert result["retrieval"]["value"] == 0 and result["semantic_gates_enabled"] is False


def test_foundry_projection_and_real_catalog_schema_without_source(manifest, config, tmp_path):
    from azure.ai.projects.models import EvaluatorVersion

    data, _ = capture(manifest, config, tmp_path)
    directory = tmp_path / "run"
    run(data, config, JsonLLM(config, sender), directory, tmp_path / "extractions")
    submitted = []

    def create_version(**kwargs):
        EvaluatorVersion(kwargs["evaluator_version"])
        assert "def grade" in kwargs["evaluator_version"]["definition"]["code_text"]
        return SimpleNamespace(version="1")

    def submit(**kwargs):
        submitted.append(kwargs)
        return SimpleNamespace(id="run-unit", status="completed", error=None, report_url="https://test")

    project = SimpleNamespace(beta=SimpleNamespace(evaluators=SimpleNamespace(create_version=create_version)))
    scored = SimpleNamespace(model_dump=lambda: {"status": "completed", "results": [{"score": 1.0}]})
    client = SimpleNamespace(evals=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(id="eval-unit"),
        runs=SimpleNamespace(create=submit, output_items=SimpleNamespace(list=lambda **kwargs: [scored])),
    ))
    publish(project, client, directory, tmp_path / "publication", "unit-test", "judge")
    assert len(submitted) == 2
    assert "TimerTrigger" not in json.dumps(submitted) and "OrderSync" not in json.dumps(submitted)
    scope = {}
    exec(CODE, scope)
    assert scope["grade"]({}, projection({
        "case_id": "private", "claim_id": "id", "status": "completed", "effective_verdict": "SUPPORTED",
        "severity": "normal", "citation_ok": True,
    })) == 1.0


def test_cli_preflight_is_offline_and_no_approval_no_capture(manifest, config, tmp_path, monkeypatch):
    paths = [tmp_path / "manifest.json", tmp_path / "config.json"]
    for path, model in zip(paths, (manifest, config), strict=True):
        path.write_text(model.model_dump_json())
    common = ["--manifest", str(paths[0]), "--config", str(paths[1])]
    assert main(["preflight", *common]) == 0
    monkeypatch.delenv("SANDBOX_READ_APPROVED", raising=False)
    output = tmp_path / "capture.json"
    assert main(["capture", *common, "--output", str(output), "--cache", str(tmp_path / "cache")]) == 1
    assert json.loads(output.read_text())["status"] == "blocked"


@pytest.mark.parametrize("edit", ["branch", "empty_facts", "candidate_judge", "same_project"])
def test_explicit_real_manifest_and_isolation_required(manifest, config, edit):
    m, c = manifest.model_dump(), config.model_dump()
    if edit == "branch":
        m["cases"][0]["integration_repo"]["commit"] = "main"
    elif edit == "empty_facts":
        m["cases"][0]["critical_facts"] = []
    elif edit == "candidate_judge":
        c["verifier"] = c["candidate"]
    else:
        c["project_endpoint"] = c["serving_project_endpoint"]
    with pytest.raises(ValueError):
        Manifest.model_validate(m)
        Config.model_validate(c)


def test_reader_rejects_undeclared_repo_before_any_get(manifest, config, tmp_path):
    get, calls, _ = transport(manifest)
    reader = Reader(manifest, config, tmp_path / "cache", get, set())
    other = manifest.cases[0].integration_repo.model_copy(update={"repository": "unapproved"})
    with pytest.raises(ValueError, match="outside"):
        reader.file(other, "/file")
    assert not calls


def test_model_input_output_deadline_and_call_bounds(config):
    config.max_calls = 1
    client = JsonLLM(config, sender)
    client.ask("extract", config.extractor, {"section": "S", "text": "source"}, Claims)
    with pytest.raises(StageError, match="call_or_deadline"):
        client.ask("extract", config.extractor, {"section": "S", "text": "source"}, Claims)
    client = JsonLLM(config, sender)
    client.deadline = 0
    with pytest.raises(StageError, match="call_or_deadline"):
        client.ask("extract", config.extractor, {}, Claims)
    assert not client.calls
    with pytest.raises(StageError, match="input_budget"):
        JsonLLM(config, sender).ask("extract", config.extractor, {"text": "x" * config.max_input_bytes}, Claims)


def test_retrieval_merges_config_and_hit_context_without_dropping_header():
    source = "\n".join(f"line{i}" for i in range(100))
    result = retrieve("`line50`", "config", {"code:/appsettings.json": source}, [], "")
    assert ("code:/appsettings.json", 1) in result.lines
    assert ("code:/appsettings.json", 51) in result.lines


@pytest.mark.parametrize("verdict,quote,effective", [
    ("STATED", "invented text", "MISSING"), ("WRONG", "invented text", "MISSING"), ("MISSING", "", "MISSING"),
])
def test_recall_quote_checks_and_negative_safety(manifest, config, tmp_path, verdict, quote, effective):
    data, _ = capture(manifest, config, tmp_path)

    def send(**kwargs):
        payload = json.loads(kwargs["input"])
        if "fact" in payload:
            return response(json.dumps({"verdict": verdict, "page_quote": quote, "reason": "UNIT TEST"}))
        return sender(**kwargs)

    result = run(data, config, JsonLLM(config, send), tmp_path / "run", tmp_path / "extractions")
    row = calibration.rows(tmp_path / "run" / "recall_results.jsonl")[0]
    assert row["effective_verdict"] == effective
    assert row["citation_ok"] is (verdict == "MISSING")
    assert "page_citation" not in row
    assert (result["overall"]["safety_status"] == "fail") is (verdict == "WRONG")


def test_semantic_errors_make_metrics_incomplete_not_partial_success():
    precision = [{"severity": "critical", "status": "error", "citation_ok": False, "effective_verdict": "ERROR"}]
    recall = [{"severity": "critical", "status": "error", "citation_ok": False, "effective_verdict": "ERROR"}]
    value = metrics(precision, recall, 1, True)
    assert value["precision"]["status"] == value["recall"]["status"] == "incomplete"
    assert value["unjudged_claims"] == value["unjudged_facts"] == 1


def test_known_secret_is_blocked_after_json_decoding(config):
    value = {"claims": [{
        "claim_id": "c1", "claim": 'password="private value"', "source_sentence": "sentence",
        "section": "S", "category": "config", "severity": "critical",
    }]}
    client = JsonLLM(config, lambda **kwargs: response(json.dumps(value)))
    with pytest.raises(StageError, match="secret_detected"):
        client.ask("extract", config.extractor, {}, Claims)
    assert len(client.calls) == 1


def test_examples_are_unrunnable_placeholders_not_golden_results():
    root = Path(__file__).parents[2]
    for model, name in ((Manifest, "manifest"), (Config, "config")):
        path = root / "evals" / f"precision-recall.{name}.example.json"
        with pytest.raises(ValueError):
            model.model_validate_json(path.read_text(encoding="utf-8"))


def test_paired_workflow_is_opt_in_no_replay_no_unapproved_publication():
    root = Path(__file__).parents[2]
    text = (root / ".github" / "workflows" / "agent-evaluation-loop.yml").read_text(encoding="utf-8")
    offline, live = text.split("\n  precision-recall:\n")
    for condition in (
        "github.event_name == 'workflow_dispatch'", "inputs.pipeline == 'precision_recall'",
        "github.ref == 'refs/heads/main'", "vars.EVAL_LOOP_ENABLED == 'true'",
        "vars.PRECISION_RECALL_ENABLED == 'true'",
    ):
        assert condition in live
    assert "default: legacy_assessments" in offline
    assert "environment: isolated-agent-evaluation" in live
    assert "persist-credentials: false" in live and "needs: offline" in live
    assert "manual-user-approved" not in live and "az login" not in live
    assert "precision_recall capture" in live and "precision_recall run" in live
    assert "precision_recall publish" in live and "not new LLM judging" in live
    assert "vars.PRECISION_RECALL_PUBLICATION_APPROVED == 'true'" in live
    assert "vars.PRECISION_RECALL_ARTIFACTS_APPROVED == 'true'" in live
    assert "vars.EVAL_LOOP_ARTIFACTS_APPROVED == 'true'" in live
    assert "replay:" not in live and "report-and-gate:" not in live
    assert "src/tools/precision_recall" in offline and "test_precision_recall.py" in offline


def test_summary_hides_source_and_failed_operation_invalidates_complete(tmp_path):
    from tools.workflow_summary import paired_decision

    path = tmp_path / "precision_recall_summary.json"
    private_json(path, {"overall": {"complete": True}, "private": "PRIVATE SOURCE"})
    assert "uncalibrated" in paired_decision(path)
    private_json(tmp_path / "operation_error.json", {"status": "blocked"})
    report = paired_decision(path)
    assert "operational error" in report and "PRIVATE SOURCE" not in report


def test_real_foundry_sdk_serializes_catalog_and_both_jsonl_runs_offline(manifest, config, tmp_path):
    import time
    from unittest.mock import MagicMock

    import httpx
    from azure.ai.projects import AIProjectClient
    from azure.core.credentials import AccessToken
    from azure.core.pipeline.transport import HttpResponse, HttpTransport

    data, _ = capture(manifest, config, tmp_path)
    directory = tmp_path / "run"
    run(data, config, JsonLLM(config, sender), directory, tmp_path / "extractions")
    catalog_requests, eval_requests = [], []

    class Response(HttpResponse):
        def __init__(self, request):
            super().__init__(request, None)
            self.status_code = 201
            self.headers = {"content-type": "application/json"}
            self.content_type = "application/json"

        def body(self):
            return json.dumps({
                **json.loads(self.request.body), "name": "unit-test", "version": "1",
            }).encode()

        def json(self):
            return json.loads(self.body())

    class Transport(HttpTransport):
        def open(self):
            pass

        def close(self):
            pass

        def __exit__(self, *_):
            self.close()

        def send(self, request, **kwargs):
            catalog_requests.append(request)
            assert request.method == "POST"
            body = json.loads(request.body)
            assert body["evaluator_type"] == "custom"
            assert body["definition"]["type"] == "code" and body["definition"]["code_text"] == CODE
            assert body["definition"]["data_schema"]["required"] == ["item"]
            return Response(request)

    def handle(request):
        eval_requests.append(request)
        if request.url.path.endswith("/evals"):
            body = json.loads(request.content)
            assert body["testing_criteria"][0]["type"] == "azure_ai_evaluator"
            assert body["testing_criteria"][0]["initialization_parameters"]["deployment_name"] == "judge"
            return httpx.Response(200, json={"id": "eval-unit"})
        if request.url.path.endswith("/runs"):
            body = json.loads(request.content)
            assert body["data_source"]["source"]["type"] == "file_content"
            assert len(body["data_source"]["source"]["content"]) == 1
            return httpx.Response(200, json={"id": "run-unit", "status": "completed", "error": None})
        assert request.url.path.endswith("/output_items")
        return httpx.Response(200, json={
            "object": "list", "has_more": False,
            "data": [{"id": "item-unit", "status": "completed", "datasource_item_id": 0,
                      "results": [{"type": "azure_ai_evaluator", "name": "precomputed", "score": 1.0}]}],
        })

    credential = MagicMock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-not-a-credential", int(time.time()) + 3600)
    with (
        AIProjectClient(endpoint=config.project_endpoint, credential=credential, transport=Transport()) as project,
        project.get_openai_client(
            api_key="unit-test-not-a-credential",
            http_client=httpx.Client(transport=httpx.MockTransport(handle)), max_retries=0,
        ) as client,
    ):
        publish(project, client, directory, tmp_path / "publication", "sdk-unit-test", "judge")
    assert len(catalog_requests) == 2 and len(eval_requests) == 6
    assert all(r.url.host == "test.services.ai.azure.com" for r in eval_requests)
    assert "OrderSync" not in "".join(r.content.decode() for r in eval_requests)
    assert json.loads((tmp_path / "publication" / "recall-completed.json").read_text())["code_scores"] == [1.0]
