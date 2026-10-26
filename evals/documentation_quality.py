"""Offline document-quality measurement and calibration; never a release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.code_eval import read_json
from tools.release_sources import load_cases

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).parent / "documentation-quality" / "three-cases.json"
VERSION: Final = "1.0.0"
CASE_IDS: Final = frozenset(
    {
        "order-sync-retry",
        "order-sync-version-isolation",
        "order-sync-dead-letter-stub",
    }
)
Id = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Kind = Literal["document", "claim", "fact"]
Identity = tuple[str, Kind, str]
LABELS: dict[Kind, tuple[str, ...]] = {
    "document": ("pass", "fail"),
    "claim": ("supported", "contradicted", "unverifiable"),
    "fact": ("covered", "missing"),
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Citation(Model):
    source_id: Id
    excerpt: Text


class Item(Model):
    id: Id
    text: Text
    citations: list[Citation] = Field(min_length=1)
    applicable: bool = True
    skip_reason: Text | None = None


class Document(Model):
    id: Id
    original_case_id: Id
    origin: Literal["synthetic_curated_example"]
    scope: Literal["technical_excerpt"]
    draft: Text
    action: Literal["proposal", "write"]
    missing_information_required: bool
    claims: list[Item]
    critical_facts: list[Item]


class Dataset(Model):
    schema_version: Literal["1.0.0"]
    dataset_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    curation_provenance: Text
    documents: list[Document] = Field(min_length=3, max_length=3)


class Row(Model):
    case_id: Id
    kind: Kind
    target_id: Id
    label: str | None
    skip_reason: Text | None = None


class Labels(Model):
    schema_version: Literal["1.0.0"]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluator_version: Literal["1.0.0"]
    guideline_blob_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    origin: Literal["external_judge", "human", "synthetic_regression", "unlabeled_template"]
    producer: Text
    producer_version: Text
    rubric_version: Literal["1.0.0"]
    rows: list[Row]


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def key(row: Row) -> Identity:
    return row.case_id, row.kind, row.target_id


def targets(dataset: Dataset) -> dict[Identity, tuple[bool, str | None]]:
    result: dict[Identity, tuple[bool, str | None]] = {}
    for doc in dataset.documents:
        result[(doc.id, "document", doc.id)] = (True, None)
        groups: list[tuple[Kind, list[Item]]] = [("claim", doc.claims), ("fact", doc.critical_facts)]
        for kind, items in groups:
            for item in items:
                identity = (doc.id, kind, item.id)
                if identity in result:
                    raise ValueError("Duplicate target identity.")
                if item.applicable == (item.skip_reason is not None):
                    raise ValueError("Only inapplicable targets require a skip reason.")
                result[identity] = item.applicable, item.skip_reason
    return result


def load_dataset(path: Path) -> tuple[Dataset, dict[str, Any], dict[str, Any]]:
    dataset = Dataset.model_validate(read_json(path))
    suite_path = ROOT / "evals" / "datasets" / "suite.json"
    suite, _ = load_cases(suite_path, ROOT)
    cases = {case["id"]: case for case in suite["cases"]}
    if len({doc.id for doc in dataset.documents}) != 3:
        raise ValueError("Three unique document IDs are required.")
    if {doc.original_case_id for doc in dataset.documents} != CASE_IDS:
        raise ValueError("Use exactly the three reviewed compatible cases.")
    targets(dataset)
    for doc in dataset.documents:
        if doc.original_case_id not in cases:
            raise ValueError("Unknown original case.")
        source_ids = cases[doc.original_case_id]["source_ids"]
        for item in doc.claims:
            if item.text not in doc.draft:
                raise ValueError("An atomic claim must be an exact passage of its document.")
        for item in doc.claims + doc.critical_facts:
            for citation in item.citations:
                if citation.source_id not in source_ids or not citation.excerpt.strip():
                    raise ValueError("Citation must name an allowlisted source and nonblank excerpt.")
                source = next(source for source in suite["sources"] if source["id"] == citation.source_id)
                text = (suite_path.parent / source["snapshot"]).read_text(encoding="utf-8")
                if source["source"] == "wiki":
                    text = json.loads(text)["content"]
                elif source["source"] == "work_item":
                    text = "\n".join(
                        str(value)
                        for name, value in json.loads(text)["fields"].items()
                        if name in {"System.Title", "System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria"}
                    )
                if citation.excerpt not in text:
                    raise ValueError("Citation excerpt is not present in the exact pinned evidence.")
    provenance = {
        "dataset_sha256": digest(
            {
                "dataset": dataset.model_dump(),
                "suite": suite,
                "evaluator_version": VERSION,
            }
        ),
        "dataset_version": dataset.dataset_version,
        "evaluator_version": VERSION,
        "guideline_blob_sha": suite["documentation_standard"]["git_blob_sha"],
        "guideline_commit": suite["documentation_standard"]["commit_sha"],
        "rubric_version": VERSION,
    }
    return dataset, provenance, suite


def label_rows(
    dataset: Dataset,
    provenance: dict[str, Any],
    labels: Labels,
) -> dict[Identity, Row]:
    for field in ("dataset_sha256", "evaluator_version", "guideline_blob_sha", "rubric_version"):
        if getattr(labels, field) != provenance[field]:
            raise ValueError("Label provenance does not match the evaluation inputs.")
    expected = targets(dataset)
    result = {}
    for row in labels.rows:
        identity = key(row)
        if identity not in expected or identity in result:
            raise ValueError("Unknown or duplicate label identity.")
        applicable, reason = expected[identity]
        if row.label is None:
            if row.skip_reason is not None:
                raise ValueError("Unlabeled rows cannot assert a skip.")
        elif not applicable:
            if row.label != "skip" or row.skip_reason != reason:
                raise ValueError("Inapplicable target must use its dataset skip reason.")
        elif row.label not in LABELS[row.kind] or row.skip_reason is not None:
            raise ValueError("Invalid label or skip for applicable target.")
        if labels.origin == "unlabeled_template" and row.label is not None:
            raise ValueError("Completed labels require explicit reviewer/judge provenance.")
        result[identity] = row
    return result


def fraction(numerator: int, denominator: int, *, complete: bool = True) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator and complete else None,
        "status": "incomplete" if not complete else "measured" if denominator else "empty_denominator",
    }


def label_provenance(labels: Labels) -> dict[str, Any]:
    return {
        "origin": labels.origin,
        "producer_sha256": digest({"producer": labels.producer, "version": labels.producer_version}),
        "labels_sha256": digest(labels.model_dump()),
        "rubric_version": labels.rubric_version,
    }


def deterministic(doc: Document) -> dict[str, Any]:
    return {
        "DQ-action-proposal-only": {"status": "pass" if doc.action == "proposal" else "fail"},
        "DQ-human-review-marker": {"status": "pass" if "Requires human review." in doc.draft else "fail"},
        "DS-20-citation-integrity": {
            "status": "pass",
            "scope": "Exact excerpts and pinned allowlist only; semantic support requires imported labels.",
        },
        "DS-22-missing-marker": {
            "status": ("pass" if "Information missing:" in doc.draft else "fail")
            if doc.missing_information_required
            else "skip",
            "reason": None if doc.missing_information_required else "No required missing-information assertion.",
        },
        "DS-23-secret-patterns": {
            "status": "fail"
            if re.search(
                r"(?i)(AccountKey\s*=|SharedAccessSignature\s*=|-----BEGIN .*PRIVATE KEY-----)",
                doc.draft,
            )
            else "pass",
            "scope": "Known credential markers only; not a privacy or secret-free guarantee.",
        },
        "DS-10-through-17-section-layout": {
            "status": "skip",
            "reason": "Technical excerpt, not a complete integration wiki page.",
        },
    }


def overall_report(documents: list[dict[str, Any]]) -> dict[str, Any]:
    coverage = {
        kind: {
            field: sum(doc["coverage"][kind][field] for doc in documents)
            for field in ("applicable", "labeled", "unjudged", "skipped")
        }
        for kind in LABELS
    }
    metrics = {}
    for metric in (
        "supported_all_claims",
        "supported_decidable_claims",
        "contradiction_rate",
        "unverifiable_rate",
        "critical_recall",
    ):
        metrics[metric] = fraction(
            sum(doc[metric]["numerator"] for doc in documents),
            sum(doc[metric]["denominator"] for doc in documents),
            complete=all(doc[metric]["status"] != "incomplete" for doc in documents),
        )
    checks = Counter(check["status"] for doc in documents for check in doc["deterministic_checks"].values())
    return {
        "aggregation": "micro",
        "coverage": coverage,
        **metrics,
        "contradiction_count": metrics["contradiction_rate"]["numerator"],
        "inapplicable_targets": [
            {"case_id": doc["case_id"], **target} for doc in documents for target in doc["inapplicable_targets"]
        ],
        "deterministic_check_counts": {status: checks[status] for status in ("pass", "fail", "skip")},
    }


def report(dataset: Dataset, provenance: dict[str, Any], labels: Labels | None = None) -> dict[str, Any]:
    imported = label_rows(dataset, provenance, labels) if labels else {}
    expected = targets(dataset)
    documents = []
    for doc in dataset.documents:
        counts: dict[str, Counter[str]] = {}
        completeness = {}
        coverage = {}
        for kind in LABELS:
            identities = [
                identity for identity, (active, _) in expected.items() if identity[:2] == (doc.id, kind) and active
            ]
            values = [
                row.label
                for identity in identities
                if (row := imported.get(identity)) is not None and row.label is not None
            ]
            counts[kind] = Counter(values)
            completeness[kind] = len(values) == len(identities)
            coverage[kind] = {
                "applicable": len(identities),
                "labeled": len(values),
                "unjudged": len(identities) - len(values),
                "skipped": sum(
                    not active for identity, (active, _) in expected.items() if identity[:2] == (doc.id, kind)
                ),
            }
        claims = counts["claim"]
        complete = completeness["claim"]
        supported, contradicted = claims["supported"], claims["contradicted"]
        all_claims = coverage["claim"]["applicable"]
        documents.append(
            {
                "case_id": doc.id,
                "original_case_id": doc.original_case_id,
                "origin": doc.origin,
                "coverage": coverage,
                "inapplicable_targets": [
                    {
                        "kind": identity[1],
                        "target_id": identity[2],
                        "status": "skip",
                        "reason": "Dataset-inapplicable; rationale is in the restricted review packet.",
                    }
                    for identity, (active, _) in expected.items()
                    if identity[0] == doc.id and not active
                ],
                "supported_all_claims": fraction(supported, all_claims, complete=complete),
                "supported_decidable_claims": fraction(supported, supported + contradicted, complete=complete),
                "contradiction_rate": fraction(contradicted, all_claims, complete=complete),
                "unverifiable_rate": fraction(claims["unverifiable"], all_claims, complete=complete),
                "critical_recall": fraction(
                    counts["fact"]["covered"],
                    coverage["fact"]["applicable"],
                    complete=completeness["fact"],
                ),
                "document_quality": next(
                    (row.label for identity, row in imported.items() if identity == (doc.id, "document", doc.id)),
                    None,
                ),
                "deterministic_checks": deterministic(doc),
            }
        )
    return {
        "provenance": provenance,
        "semantic_gates_enabled": False,
        "label_provenance": label_provenance(labels) if labels else None,
        "documents": documents,
        "overall": overall_report(documents),
    }


def calibration(
    dataset: Dataset,
    provenance: dict[str, Any],
    judge: Labels,
    human: Labels,
) -> dict[str, Any]:
    if human.origin not in {"human", "synthetic_regression"}:
        raise ValueError("Reference labels must be human-authored or explicitly synthetic regression labels.")
    if judge.origin not in {"external_judge", "synthetic_regression"}:
        raise ValueError("Judge labels must be external results or explicitly synthetic regression labels.")
    predicted, reference = label_rows(dataset, provenance, judge), label_rows(dataset, provenance, human)
    expected = targets(dataset)
    by_kind = {}
    for kind, categories in LABELS.items():
        identities = [identity for identity, (active, _) in expected.items() if active and identity[1] == kind]
        pairs = [
            (reference[identity].label, predicted[identity].label)
            for identity in sorted(identities)
            if identity in predicted
            and identity in reference
            and reference[identity].label is not None
            and predicted[identity].label is not None
        ]
        matrix = {actual: {prediction: 0 for prediction in categories} for actual in categories}
        for actual, prediction in pairs:
            assert actual is not None and prediction is not None
            matrix[actual][prediction] += 1
        n = len(pairs)
        correct = sum(actual == prediction for actual, prediction in pairs)
        agreement = correct / n if n else None
        chance = (
            sum(
                sum(matrix[label].values()) * sum(matrix[actual][label] for actual in categories)
                for label in categories
            )
            / n**2
            if n
            else None
        )
        by_kind[kind] = {
            "paired": n,
            "applicable": len(identities),
            "unpaired": len(identities) - n,
            "agreement": fraction(correct, n),
            "confusion": matrix,
            "confusion_orientation": "rows=human, columns=judge",
            "kappa": (agreement - chance) / (1 - chance)
            if agreement is not None and chance is not None and chance != 1
            else None,
            "kappa_status": "measured" if n and chance != 1 else "empty_denominator" if not n else "degenerate",
        }
        if kind == "claim":
            by_kind[kind]["contradiction_sensitivity"] = fraction(
                matrix["contradicted"]["contradicted"],
                sum(matrix["contradicted"].values()),
            )
    return {
        "provenance": provenance,
        "semantic_gates_enabled": False,
        "calibration_state": "synthetic_regression_only"
        if "synthetic_regression" in {judge.origin, human.origin}
        else "external_judge_vs_human",
        "judge_provenance": label_provenance(judge),
        "human_provenance": label_provenance(human),
        "by_kind": by_kind,
    }


def export_template(dataset: Dataset, provenance: dict[str, Any], suite: dict[str, Any], path: Path) -> None:
    destination = path.resolve()
    ignored = [ROOT / "evals" / "documentation-quality" / "private", ROOT / "evals" / "results"]
    if destination.is_relative_to(ROOT) and not any(destination.is_relative_to(folder) for folder in ignored):
        raise ValueError("Review packets inside the repository must use an ignored local-output directory.")
    template = Labels(
        schema_version=VERSION,
        dataset_sha256=provenance["dataset_sha256"],
        evaluator_version=VERSION,
        guideline_blob_sha=provenance["guideline_blob_sha"],
        origin="unlabeled_template",
        producer="REPLACE_WITH_REVIEWER_OR_JUDGE",
        producer_version="REPLACE_WITH_VERSION",
        rubric_version=VERSION,
        rows=[
            Row(case_id=case, kind=kind, target_id=target, label=None)
            for case, kind, target in sorted(targets(dataset))
        ],
    )
    selected_cases = {doc.original_case_id for doc in dataset.documents}
    case_source_ids = {case["id"]: case["source_ids"] for case in suite["cases"] if case["id"] in selected_cases}
    selected_sources = {source_id for ids in case_source_ids.values() for source_id in ids}
    payload = {
        "instructions": "Restricted review packet. Fill labels in labels only; import that object as a labels file.",
        "rubric": {
            "claim": "supported / contradicted / unverifiable against only the case allowlist; no world knowledge.",
            "fact": "covered / missing in the draft; semantic equivalence is a reviewer judgment.",
            "document": "pass / fail: useful, factual technical excerpt with honest limitations and review notice.",
            "skip": "Only dataset-inapplicable targets may use skip, with the exact dataset skip_reason.",
            "atomicity": "Curated spans, not automatic extraction. Review completeness and atomicity manually.",
        },
        "provenance": provenance,
        "dataset": dataset.model_dump(),
        "case_source_ids": case_source_ids,
        "source_catalog": [source for source in suite["sources"] if source["id"] in selected_sources],
        "documentation_standard": suite["documentation_standard"],
        "labels": template.model_dump(),
    }
    # Exclusive creation prevents clobbering owner annotations. POSIX permissions are advisory on Windows.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser("measure")
    measure.add_argument("--labels", type=Path)
    export = commands.add_parser("export")
    export.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("calibrate")
    compare.add_argument("--judge", type=Path, required=True)
    compare.add_argument("--human", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        dataset, provenance, suite = load_dataset(args.dataset)
        if args.command == "export":
            export_template(dataset, provenance, suite, args.output)
            output = {"state": "unlabeled_template_exported", "semantic_gates_enabled": False}
        elif args.command == "calibrate":
            output = calibration(
                dataset,
                provenance,
                Labels.model_validate(read_json(args.judge)),
                Labels.model_validate(read_json(args.human)),
            )
        else:
            labels = Labels.model_validate(read_json(args.labels)) if args.labels else None
            output = report(dataset, provenance, labels)
    except (OSError, ValueError, KeyError):
        # Do not echo raw source, reviewer content, paths, or validation-error payloads into summaries.
        print("Documentation quality input/evaluator error; inspect restricted inputs locally.", file=sys.stderr)
        return 2
    print(json.dumps(output, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
