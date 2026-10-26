"""Synthetic regression labels exercise math, not observed semantic calibration."""

import json
import os
import runpy
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).parents[2]
DQ = SimpleNamespace(**runpy.run_path(str(ROOT / "evals" / "documentation_quality.py")))


@pytest.fixture
def inputs():
    return DQ.load_dataset(DQ.DEFAULT_DATASET)


def labels_for(dataset, provenance, changes=None, origin="synthetic_regression"):
    rows = []
    for (case, kind, target), (applicable, reason) in sorted(DQ.targets(dataset).items()):
        label = {"claim": "supported", "fact": "covered", "document": "pass"}[kind] if applicable else "skip"
        label = (changes or {}).get((case, kind, target), label)
        rows.append(
            {
                "case_id": case,
                "kind": kind,
                "target_id": target,
                "label": label,
                "skip_reason": reason if label == "skip" else None,
            }
        )
    return DQ.Labels(
        schema_version="1.0.0",
        dataset_sha256=provenance["dataset_sha256"],
        evaluator_version="1.0.0",
        guideline_blob_sha=provenance["guideline_blob_sha"],
        origin=origin,
        producer="Synthetic regression fixture, not a real reviewer",
        producer_version="test-1",
        rubric_version="1.0.0",
        rows=rows,
    )


def test_three_pinned_cases_and_unmeasured_semantics(inputs):
    dataset, provenance, _ = inputs
    assert [doc.original_case_id for doc in dataset.documents] == [
        "order-sync-retry",
        "order-sync-version-isolation",
        "order-sync-dead-letter-stub",
    ]
    assert DQ.load_dataset(DQ.DEFAULT_DATASET)[1] == provenance
    report = DQ.report(dataset, provenance)
    assert report["semantic_gates_enabled"] is False
    assert report["label_provenance"] is None
    for doc in report["documents"]:
        assert doc["supported_all_claims"]["value"] is None
        assert doc["critical_recall"]["status"] == "incomplete"
        assert doc["document_quality"] is None
        assert doc["deterministic_checks"]["DS-20-citation-integrity"]["status"] == "pass"
    assert report["documents"][1]["coverage"]["fact"]["skipped"] == 1


def test_distinct_claim_denominators_recall_and_sanitized_output(inputs):
    dataset, provenance, _ = inputs
    changes = {
        ("retry-draft", "claim", "timeout"): "unverifiable",
        ("stub-draft", "claim", "print-only"): "contradicted",
        ("retry-draft", "fact", "backoff"): "missing",
        ("retry-draft", "document", "retry-draft"): "fail",
    }
    labels = labels_for(dataset, provenance, changes)
    result = DQ.report(dataset, provenance, labels)
    retry, _, stub = result["documents"]
    assert retry["supported_all_claims"]["value"] == 0.5
    assert retry["supported_decidable_claims"]["value"] == 1
    assert retry["unverifiable_rate"]["value"] == 0.5
    assert retry["critical_recall"]["value"] == 0.8
    assert retry["document_quality"] == "fail"
    assert stub["contradiction_rate"]["value"] == 0.5
    assert stub["supported_decidable_claims"]["value"] == 0.5
    summary = json.dumps(result)
    assert dataset.documents[0].draft not in summary
    assert "orders-confirmed-failed" not in summary
    assert labels.producer not in summary
    assert "source_catalog" not in summary


def test_partial_and_empty_denominators(inputs):
    dataset, provenance, _ = inputs
    labels = labels_for(dataset, provenance)
    labels.rows = [
        row for row in labels.rows if (row.case_id, row.kind, row.target_id) != ("retry-draft", "claim", "timeout")
    ]
    retry = DQ.report(dataset, provenance, labels)["documents"][0]
    assert retry["supported_all_claims"]["status"] == "incomplete"
    assert retry["supported_all_claims"]["value"] is None
    assert retry["coverage"]["claim"]["unjudged"] == 1
    labels = labels_for(
        dataset,
        provenance,
        {
            ("retry-draft", "claim", "timeout"): "unverifiable",
            ("retry-draft", "claim", "attempts"): "unverifiable",
        },
    )
    retry = DQ.report(dataset, provenance, labels)["documents"][0]
    assert retry["supported_decidable_claims"] == {
        "value": None,
        "status": "empty_denominator",
        "numerator": 0,
        "denominator": 0,
    }
    assert retry["supported_all_claims"]["value"] == 0
    assert DQ.fraction(0, 0)["status"] == "empty_denominator"


def test_calibration_known_matrix_kappa_and_contradiction_sensitivity(inputs):
    dataset, provenance, _ = inputs
    human = labels_for(
        dataset,
        provenance,
        {
            ("retry-draft", "claim", "attempts"): "contradicted",
            ("retry-draft", "claim", "timeout"): "contradicted",
            ("stub-draft", "claim", "queue"): "unverifiable",
        },
    )
    judge = labels_for(
        dataset,
        provenance,
        {
            ("retry-draft", "claim", "attempts"): "contradicted",
            ("stub-draft", "claim", "queue"): "unverifiable",
        },
    )
    result = DQ.calibration(dataset, provenance, judge, human)
    claims = result["by_kind"]["claim"]
    assert result["calibration_state"] == "synthetic_regression_only"
    assert claims["paired"] == 6
    assert claims["agreement"]["value"] == pytest.approx(5 / 6)
    # Actual margins = (3,2,1), predicted = (4,1,1); chance = 15/36.
    assert claims["kappa"] == pytest.approx(5 / 7)
    assert claims["contradiction_sensitivity"]["value"] == 0.5
    assert claims["confusion"]["contradicted"]["supported"] == 1
    assert result["by_kind"]["document"]["kappa_status"] == "degenerate"
    assert result["by_kind"]["fact"]["applicable"] == 10


def test_calibration_missing_pairs_and_real_provenance(inputs):
    dataset, provenance, _ = inputs
    judge = labels_for(dataset, provenance, origin="external_judge")
    human = labels_for(dataset, provenance, origin="human")
    human.rows = []
    result = DQ.calibration(dataset, provenance, judge, human)
    assert result["calibration_state"] == "external_judge_vs_human"
    assert result["by_kind"]["claim"]["unpaired"] == 6
    assert result["by_kind"]["claim"]["agreement"]["value"] is None
    assert result["by_kind"]["claim"]["kappa_status"] == "empty_denominator"
    assert result["by_kind"]["claim"]["contradiction_sensitivity"]["value"] is None
    with pytest.raises(ValueError, match="Reference labels"):
        DQ.calibration(dataset, provenance, judge, judge)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "unknown",
        "stale",
        "invalid-label",
        "skip-applicable",
        "bad-skip",
        "template",
    ],
)
def test_reject_bad_label_joins_and_provenance(inputs, mutation):
    dataset, provenance, _ = inputs
    labels = labels_for(dataset, provenance)
    if mutation == "duplicate":
        labels.rows.append(labels.rows[0])
    elif mutation == "unknown":
        labels.rows[0].target_id = "unknown"
    elif mutation == "stale":
        labels.dataset_sha256 = "0" * 64
    elif mutation == "invalid-label":
        labels.rows[0].label = "maybe"
    elif mutation == "skip-applicable":
        labels.rows[0].label = "skip"
        labels.rows[0].skip_reason = "not convenient"
    elif mutation == "bad-skip":
        next(row for row in labels.rows if row.label == "skip").skip_reason = "wrong reason"
    elif mutation == "template":
        labels.origin = "unlabeled_template"
    with pytest.raises(ValueError):
        DQ.report(dataset, provenance, labels)


@pytest.mark.parametrize("mutation", ["quote", "cross-version", "claim-span", "duplicate-case", "skip-reason"])
def test_reject_bad_dataset_evidence(inputs, tmp_path, mutation):
    dataset, _, _ = inputs
    raw = deepcopy(dataset.model_dump())
    if mutation == "quote":
        raw["documents"][0]["claims"][0]["citations"][0]["excerpt"] = '"maxAttempts": 999'
    elif mutation == "cross-version":
        raw["documents"][1]["claims"][0]["citations"][0]["source_id"] = "pr62-settings"
    elif mutation == "claim-span":
        raw["documents"][0]["claims"][0]["text"] = "Unlisted claim."
    elif mutation == "duplicate-case":
        raw["documents"][0]["original_case_id"] = raw["documents"][1]["original_case_id"]
    elif mutation == "skip-reason":
        raw["documents"][0]["claims"][0]["skip_reason"] = "but applicable"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        DQ.load_dataset(path)


def test_deterministic_failures_are_quality_not_operational_errors(inputs):
    doc = inputs[0].documents[0].model_copy(deep=True)
    doc.action = "write"
    doc.draft = "AccountKey=synthetic-canary"
    doc.missing_information_required = True
    checks = DQ.deterministic(doc)
    assert checks["DQ-action-proposal-only"]["status"] == "fail"
    assert checks["DQ-human-review-marker"]["status"] == "fail"
    assert checks["DS-22-missing-marker"]["status"] == "fail"
    assert checks["DS-23-secret-patterns"]["status"] == "fail"
    assert checks["DS-10-through-17-section-layout"]["status"] == "skip"


def test_export_is_unlabeled_restricted_and_never_overwrites(inputs, tmp_path):
    dataset, provenance, suite = inputs
    path = tmp_path / "packet.json"
    DQ.export_template(dataset, provenance, suite, path)
    packet = json.loads(path.read_text(encoding="utf-8"))
    assert packet["dataset"]["curation_provenance"].startswith("Synthetic")
    assert all(row["label"] is None for row in packet["labels"]["rows"])
    labels = DQ.Labels.model_validate(packet["labels"])
    assert DQ.report(dataset, provenance, labels)["documents"][0]["critical_recall"]["value"] is None
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        DQ.export_template(dataset, provenance, suite, path)
    with pytest.raises(ValueError, match="ignored local-output"):
        DQ.export_template(dataset, provenance, suite, ROOT / "evals" / "never-create-review-packet.json")


def test_cli_exit_codes_no_raw_error_content(inputs, tmp_path, capsys):
    assert DQ.main(["measure"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["semantic_gates_enabled"] is False
    bad = tmp_path / "private.json"
    bad.write_text('{"private":"NEVER-ECHO-THIS","private":1}', encoding="utf-8")
    assert DQ.main(["measure", "--labels", str(bad)]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "input/evaluator error" in output.err
    assert "NEVER-ECHO-THIS" not in output.err
    dataset, provenance, _ = inputs
    failing = labels_for(dataset, provenance, {("retry-draft", "document", "retry-draft"): "fail"})
    bad.write_text(failing.model_dump_json(), encoding="utf-8")
    assert DQ.main(["measure", "--labels", str(bad)]) == 0
    assert json.loads(capsys.readouterr().out)["documents"][0]["document_quality"] == "fail"


def test_strict_input_schema(inputs):
    raw = inputs[0].model_dump()
    raw["documents"][0]["missing_information_required"] = "true"
    with pytest.raises(ValidationError):
        DQ.Dataset.model_validate(raw)


def test_empty_claims_and_facts_are_not_perfect_scores(inputs):
    dataset, provenance, _ = inputs
    dataset = dataset.model_copy(deep=True)
    dataset.documents[0].claims = []
    dataset.documents[0].critical_facts = []
    report = DQ.report(dataset, provenance)
    doc = report["documents"][0]
    for metric in ("supported_all_claims", "supported_decidable_claims", "critical_recall"):
        assert doc[metric]["value"] is None
        assert doc[metric]["status"] == "empty_denominator"


def test_label_order_does_not_change_metrics(inputs):
    dataset, provenance, _ = inputs
    labels = labels_for(dataset, provenance)
    baseline = DQ.report(dataset, provenance, labels)
    labels.rows.reverse()
    reversed_report = DQ.report(dataset, provenance, labels)
    # The raw label digest records the submitted file representation, not just its scores.
    assert baseline["documents"] == reversed_report["documents"]


def test_cli_export_and_calibration_are_offline(inputs, tmp_path, monkeypatch, capsys):
    import socket

    def deny_network(*args, **kwargs):
        pytest.fail("Local document measurement must not use the network.")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    packet = tmp_path / "packet.json"
    assert DQ.main(["export", "--output", str(packet)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "unlabeled_template_exported"
    assert DQ.main(["export", "--output", str(packet)]) == 2
    assert "input/evaluator error" in capsys.readouterr().err
    dataset, provenance, _ = inputs
    judge = tmp_path / "judge.json"
    human = tmp_path / "human.json"
    judge.write_text(labels_for(dataset, provenance).model_dump_json(), encoding="utf-8")
    human.write_text(labels_for(dataset, provenance).model_dump_json(), encoding="utf-8")
    assert DQ.main(["calibrate", "--judge", str(judge), "--human", str(human)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["calibration_state"] == "synthetic_regression_only"
    assert output["by_kind"]["claim"]["agreement"]["value"] == 1
    assert output["by_kind"]["claim"]["contradiction_sensitivity"]["status"] == "empty_denominator"
