"""Restricted blind labelling exports and agreement scoring; never enable a release gate."""

import csv
import io
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from tools.sandbox_eval import digest

from .pipeline import fraction
from .sources import safe_value

LABELS = {
    "precision": {"SUPPORTED", "CONTRADICTED", "NOT_VERIFIABLE"},
    "recall": {"STATED", "WRONG", "MISSING"},
}
FIELDS = ["row_id", "stage", "input_sha256", "input_json", "label", "reviewer"]


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def export(run: Path, capture: dict[str, Any], output: Path) -> None:
    by_case = {c["case"]["id"]: c for c in capture["cases"]}
    sheets = []
    summary = json.loads((run / "precision_recall_summary.json").read_text(encoding="utf-8"))
    if summary["capture_sha256"] != capture["sha256"]:
        raise ValueError("Calibration capture does not match run.")
    for stage in LABELS:
        for row in rows(run / (stage + "_results.jsonl")):
            data = by_case[row["case_id"]]
            if stage == "precision":
                evidence = json.loads(
                    (run / (row["case_id"] + "-" + row["claim_id"] + "-evidence.json")).read_text(encoding="utf-8"),
                )
                payload = {"claim": row["claim"], "source_sentence": row["source_sentence"],
                           "evidence": evidence["evidence"]}
                target = row["claim_id"]
            else:
                payload = {"fact": row["fact"], "page": data["page"]}
                target = row["fact_id"]
            sheets.append({
                "row_id": f"{row['case_id']}:{target}", "stage": stage,
                "input_sha256": digest(json.dumps(payload, sort_keys=True)),
                "input_json": json.dumps(payload, sort_keys=True), "label": "", "reviewer": "",
            })
    for case_id, data in by_case.items():
        payload = {"page": data["page"], "heading_context_required": True}
        sheets.append({
            "row_id": case_id, "stage": "extract",
            "input_sha256": digest(json.dumps(payload, sort_keys=True)),
            "input_json": json.dumps(payload, sort_keys=True), "label": "", "reviewer": "",
        })
    safe_value(sheets)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(sheets)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
        file.write(buffer.getvalue())


def agreement(pairs: list[tuple[str, str]], labels: set[str]) -> dict[str, Any]:
    matrix = {a: {b: 0 for b in sorted(labels)} for a in sorted(labels)}
    for actual, predicted in pairs:
        matrix[actual][predicted] += 1
    n = len(pairs)
    correct = sum(a == b for a, b in pairs)
    chance = sum(
        sum(matrix[a].values()) * sum(matrix[b][a] for b in labels) for a in labels
    ) / n**2 if n else None
    return {
        "agreement": fraction(correct, n), "confusion": matrix, "rows": n,
        "kappa": (correct / n - chance) / (1 - chance) if n and chance is not None and chance != 1 else None,
        "kappa_status": "empty" if not n else "degenerate" if chance == 1 else "measured",
    }


def load_sheet(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        sheet = list(csv.DictReader(file))
    result = {}
    for row in sheet:
        if set(row) != set(FIELDS):
            raise ValueError("Unexpected calibration columns.")
        stage = row["stage"]
        if (
            stage not in {*LABELS, "extract"} or not row["reviewer"].strip() or not row["label"].strip()
            or digest(json.dumps(json.loads(row["input_json"]), sort_keys=True)) != row["input_sha256"]
        ):
            raise ValueError("Incomplete labels, reviewer or calibration input provenance.")
        if stage in LABELS and row["label"] not in LABELS[stage]:
            raise ValueError("Invalid stage label.")
        identity = stage, row["row_id"]
        if identity in result:
            raise ValueError("Duplicate calibration row.")
        result[identity] = row
    return result


def score(run: Path, first: Path, second: Path) -> dict[str, Any]:
    a, b = load_sheet(first), load_sheet(second)
    if not a or set(a) != set(b):
        raise ValueError("Both engineers must label the same complete sheet.")
    for key in a:
        if (
            a[key]["input_sha256"] != b[key]["input_sha256"]
            or a[key]["reviewer"] == b[key]["reviewer"]
        ):
            raise ValueError("Independent reviewers with identical inputs are required.")
    stages = {}
    for stage, labels in LABELS.items():
        predicted = {}
        for row in rows(run / (stage + "_results.jsonl")):
            target = row["claim_id"] if stage == "precision" else row["fact_id"]
            predicted[(stage, f"{row['case_id']}:{target}")] = row
        keys = [k for k in a if k[0] == stage]
        if set(keys) != set(predicted):
            raise ValueError("Calibration labels and observed verdict rows differ.")
        if any(a[k]["input_sha256"] != predicted[k]["calibration_input_sha256"] for k in keys):
            raise ValueError("Calibration input differs from the observed judge input.")
        human = agreement([(a[k]["label"], b[k]["label"]) for k in keys], labels)
        consensus = [k for k in keys if a[k]["label"] == b[k]["label"]]
        pairs = [(a[k]["label"], predicted[k]["effective_verdict"]) for k in consensus]
        valid = [(actual, prediction) for actual, prediction in pairs if prediction in labels]
        judge = agreement(valid, labels)
        bad = [
            {"row_id": k[1], "human": a[k]["label"], "judge": predicted[k]["effective_verdict"],
             "reason": predicted[k].get("reason"), "citation_ok": predicted[k]["citation_ok"]}
            for k in consensus if a[k]["label"] != predicted[k]["effective_verdict"]
        ]
        contradiction = [k for k in consensus if a[k]["label"] == "CONTRADICTED"]
        kappa = human["kappa"]
        judge_kappa = judge["kappa"]
        sensitivity = fraction(
            sum(predicted[k]["effective_verdict"] == "CONTRADICTED" for k in contradiction), len(contradiction),
        ) if stage == "precision" else None
        enough = len(consensus) >= (150 if stage == "precision" else 50)
        ready = (
            enough and len(pairs) == len(valid) and kappa is not None and kappa >= 0.8
            and judge_kappa is not None and judge_kappa >= 0.8
            and (stage != "precision" or sensitivity is not None
                 and sensitivity["value"] is not None and sensitivity["value"] >= 0.9)
        )
        stages[stage] = {
            "human_vs_human": human, "consensus_rows": len(consensus), "judge_vs_consensus": judge,
            "unjudged": len(pairs) - len(valid), "disagreements": bad,
            "human_guide_ready": kappa is not None and kappa >= 0.8,
            "required_rows": 150 if stage == "precision" else 50,
            "contradiction_sensitivity": sensitivity, "stage_target_observed": ready,
            "prompt_versions": sorted({row["prompt_version"] for row in predicted.values()}),
            "model_deployments": [json.loads(value) for value in sorted({
                json.dumps(row["model"], sort_keys=True) for row in predicted.values()
            })],
        }
    return {
        "semantic_gates_enabled": False, "stages": stages,
        "extraction": "Blind human claim lists exported; semantic alignment requires human adjudication.",
        "retrieval": "Use coverage review with at least 50 human-supported claims and exact needed file labels.",
        "production_fact_selection": "deferred",
    }


def coverage_review(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score explicit human adjudications, not guessed text similarity or fabricated labels."""
    counts: Counter[str] = Counter()
    seen = set()
    for row in records:
        if (
            row["stage"] not in {"retrieval", "extract"} or row["origin"] != "human_adjudication"
            or not row["review_reference"] or not row["input_sha256"]
        ):
            raise ValueError("Human adjudication and input provenance are required.")
        key = row["stage"], row["input_sha256"]
        if key in seen:
            raise ValueError("Duplicate human coverage input.")
        seen.add(key)
        if row["stage"] == "retrieval":
            needed, found = set(row["needed_files"]), set(row["retrieved_files"])
            if not needed:
                raise ValueError("Retrieval labels must identify needed files.")
            counts["retrieval_total"] += 1
            counts["retrieval_found"] += needed.issubset(found)
        else:
            expected = row["human_claims"]
            if not expected or any(
                type(c["matched"]) is not bool or c["severity"] not in {"critical", "normal"} for c in expected
            ):
                raise ValueError("Extraction requires explicit claim alignment adjudications.")
            counts["documents"] += 1
            for claim in expected:
                counts["total"] += 1
                counts["found"] += claim["matched"]
                if claim["severity"] == "critical":
                    counts["critical_total"] += 1
                    counts["critical_found"] += claim["matched"]
    return {
        "semantic_gates_enabled": False,
        "retrieval": fraction(counts["retrieval_found"], counts["retrieval_total"]),
        "extraction_all": fraction(counts["found"], counts["total"]),
        "extraction_critical": fraction(counts["critical_found"], counts["critical_total"]),
        "documents": counts["documents"], "counts": dict(counts),
    }
