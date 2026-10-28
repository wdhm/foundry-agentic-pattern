"""The two chains run together; partial work produces review/error states, never a pass."""

import json
import os
import random
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.sandbox_eval import digest

from .llm import PROMPTS, JsonLLM, StageError
from .models import Claim, Claims, Config, PrecisionVerdict, RecallVerdict
from .retrieval import citations_ok, retrieve
from .sources import private_json, safe_value

CANONICAL_VERSION = "1"


def sections(page: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    headings: list[tuple[int, str]] = []
    content: list[str] = []
    fence: str | None = None
    for line in page.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if fence is None else None
        if heading:
            if "\n".join(content).strip():
                result.append((" > ".join(h for _, h in headings) or "Introduction", "\n".join(content)))
            level = len(heading[1])
            headings = [(n, h) for n, h in headings if n < level] + [(level, heading[2])]
            content = []
        else:
            content.append(line)
    if "\n".join(content).strip():
        result.append((" > ".join(h for _, h in headings) or "Introduction", "\n".join(content)))
    return result


def canonicalize(claims: list[Claim]) -> list[Claim]:
    unique: dict[str, Claim] = {}
    for claim in claims:
        identity = digest(json.dumps({
            "version": CANONICAL_VERSION, "claim": claim.claim, "sentence": claim.source_sentence,
            "section": claim.section,
        }, sort_keys=True))
        item = claim.model_copy(update={"claim_id": "c-" + identity[:24]})
        if claim.category in {"auth", "endpoint", "config", "schedule", "error_handling", "data"}:
            item.severity = "critical"
        previous = unique.get(identity)
        if previous is not None and previous.category != item.category:
            raise StageError("extract", "conflicting_duplicate_categories")
        if previous is not None and previous.severity == "critical":
            item.severity = "critical"
        unique[identity] = item
    return [unique[key] for key in sorted(unique)]


def select(claims: list[Claim], config: Config) -> list[Claim]:
    critical = [c for c in claims if c.severity == "critical"]
    normal = [c for c in claims if c.severity == "normal"]
    sampled = random.Random(config.seed).sample(normal, min(config.normal_sample, len(normal)))
    return sorted(critical + sampled, key=lambda c: c.claim_id)


def fraction(n: int, d: int, *, complete: bool = True) -> dict[str, Any]:
    return {
        "numerator": n, "denominator": d, "value": n / d if d and complete else None,
        "status": "incomplete" if not complete else "measured" if d else "empty_denominator",
    }


def metrics(
    precision: list[dict[str, Any]], recall: list[dict[str, Any]], extracted: int, extraction_complete: bool,
) -> dict[str, Any]:
    p = Counter(row["effective_verdict"] for row in precision)
    r = Counter(row["effective_verdict"] for row in recall)
    complete = extraction_complete and bool(extracted) and bool(precision) and bool(recall) and all(
        row["status"] == "completed" and row["citation_ok"] for row in [*precision, *recall]
    )
    critical_contradictions = sum(
        row["severity"] == "critical" and row.get("verdict") == "CONTRADICTED" for row in precision
    )
    critical_wrong = sum(row["severity"] == "critical" and row.get("verdict") == "WRONG" for row in recall)
    wrong = sum(row.get("verdict") == "WRONG" for row in recall)
    precision_complete = extraction_complete and not p["ERROR"]
    recall_complete = not r["ERROR"]
    return {
        "precision": fraction(p["SUPPORTED"], p["SUPPORTED"] + p["CONTRADICTED"], complete=precision_complete),
        "supported_all_selected": fraction(p["SUPPORTED"], len(precision), complete=precision_complete),
        "not_verifiable_rate": fraction(p["NOT_VERIFIABLE"], len(precision), complete=precision_complete),
        "coverage": fraction(sum(row["status"] == "completed" for row in precision), extracted,
                             complete=extraction_complete),
        "recall": fraction(r["STATED"], len(recall), complete=recall_complete),
        "critical_recall": fraction(
            sum(row["severity"] == "critical" and row["effective_verdict"] == "STATED" for row in recall),
            sum(row["severity"] == "critical" for row in recall),
            complete=recall_complete,
        ),
        "contradictions": p["CONTRADICTED"], "critical_contradictions": critical_contradictions,
        "wrong_facts": wrong, "critical_wrong_facts": critical_wrong,
        "precision_failures_from_recall": wrong,
        "unjudged_claims": p["ERROR"], "unjudged_facts": r["ERROR"],
        "complete": complete,
        "safety_status": (
            "fail" if critical_contradictions or critical_wrong else "review" if not complete else "observed"
        ),
        "semantic_gates_enabled": False, "calibration_state": "not_calibrated",
    }


def run(
    capture: dict[str, Any], config: Config, llm: JsonLLM, output: Path, extraction_cache: Path,
) -> dict[str, Any]:
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    precision: list[dict[str, Any]] = []
    recall: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    private_json(output / "provenance.json", {
        "capture_sha256": capture["sha256"], "config": config.model_dump(mode="json"),
        "prompt_versions": {stage: value[0] for stage, value in PROMPTS.items()},
        "canonicalization_version": CANONICAL_VERSION,
        "gate": "disabled_pending_human_calibration", "page_generation": "not_performed",
        "publication": "not_performed", "concurrency": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "implementation_sha256": {
            path.name: digest(path.read_text(encoding="utf-8")) for path in sorted(Path(__file__).parent.glob("*.py"))
        },
    })
    for data in capture["cases"]:
        case_id, page = data["case"]["id"], data["page"]
        start_p, start_r = len(precision), len(recall)
        claims: list[Claim] = []
        errors: list[dict[str, str]] = []
        key = digest(json.dumps({
            "page": page, "page_file": data["page_file"], "prompt": PROMPTS["extract"],
            "model": config.extractor.model_dump(), "canonicalization": CANONICAL_VERSION,
            "schema": Claims.model_json_schema(),
        }, sort_keys=True))
        cache_path = extraction_cache / (key + ".json")
        extraction_start = len(llm.calls)
        if cache_path.exists():
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            if saved["input_sha256"] != key or saved["sha256"] != digest(json.dumps(saved["claims"], sort_keys=True)):
                raise StageError("extract", "cache_integrity")
            claims = [Claim.model_validate(value) for value in saved["claims"]]
            if canonicalize(claims) != claims:
                raise StageError("extract", "noncanonical_cache")
            safe_value(saved)
        else:
            for section, chunk in sections(page):
                def check(result: Claims, section: str = section, chunk: str = chunk) -> None:
                    if any(c.section != section or c.source_sentence not in chunk for c in result.claims):
                        raise ValueError("Invalid source sentence or heading handoff.")

                try:
                    result = llm.ask("extract", config.extractor, {"section": section, "text": chunk}, Claims, check)
                    claims.extend(result.claims)
                except StageError as exc:
                    errors.append({"stage": exc.stage, "code": exc.code})
            claims = canonicalize(claims)
            if not errors:
                values = [c.model_dump() for c in claims]
                private_json(cache_path, {
                    "input_sha256": key, "sha256": digest(json.dumps(values, sort_keys=True)), "claims": values,
                    "extraction_calls": llm.calls[extraction_start:],
                })
        chosen = select(claims, config)
        private_json(output / (case_id + "-selection.json"), {
            "extraction_key": key, "extraction_complete": not errors,
            "claims": [c.model_dump() for c in claims], "selected_ids": [c.claim_id for c in chosen],
            "seed": config.seed, "normal_sample": config.normal_sample,
            "strata": {
                severity: {"extracted": sum(c.severity == severity for c in claims),
                           "selected": sum(c.severity == severity for c in chosen)}
                for severity in ("critical", "normal")
            }, "errors": errors,
        })
        for claim in chosen:
            evidence = retrieve(
                claim.claim, claim.category, data["files"], data["touched"], data["diff"], config.evidence_bytes,
            )
            row: dict[str, Any] = {
                "case_id": case_id, **claim.model_dump(), "status": "error", "citation_ok": False,
                "effective_verdict": "ERROR", "page_file": data["page_file"],
                "page_origin": data["case"]["page"]["origin"],
                "retrieved_files": evidence.files, "retrieval_truncated": evidence.truncated,
                "evidence_sha256": digest(evidence.text), "prompt_version": PROMPTS["precision"][0],
                "model": config.verifier.model_dump(), "extraction_key": key,
            }
            payload = {"claim": claim.claim, "source_sentence": claim.source_sentence, "evidence": evidence.text}
            row["calibration_input_sha256"] = digest(json.dumps(payload, sort_keys=True))
            before = len(llm.calls)
            try:
                verdict = llm.ask("precision", config.verifier, payload, PrecisionVerdict)
                ok = citations_ok(verdict.evidence_quotes, evidence, allow_empty=verdict.verdict == "NOT_VERIFIABLE")
                row.update(verdict.model_dump(), status="completed", citation_ok=ok,
                           effective_verdict=verdict.verdict if ok else "NOT_VERIFIABLE",
                           redacted_citation=any("<REDACTED>" in q.text for q in verdict.evidence_quotes))
            except StageError as exc:
                row["error"] = {"stage": exc.stage, "code": exc.code}
            row["calls"] = llm.calls[before:]
            precision.append(row)
            private_json(output / (case_id + "-" + claim.claim_id + "-evidence.json"), {
                "evidence": evidence.text, "lines": [
                    {"file": file, "line": line, "text": text} for (file, line), text in evidence.lines.items()
                ],
            })
        for fact in data["case"]["critical_facts"]:
            row = {
                "case_id": case_id, **fact, "fact_source": "engineer_fixed_list", "status": "error",
                "effective_verdict": "ERROR", "citation_ok": False, "page_file": data["page_file"],
                "page_origin": data["case"]["page"]["origin"], "prompt_version": PROMPTS["recall"][0],
                "model": config.verifier.model_dump(),
            }
            payload = {"fact": fact["fact"], "page": page}
            row["calibration_input_sha256"] = digest(json.dumps(payload, sort_keys=True))
            before = len(llm.calls)
            try:
                result_r = llm.ask("recall", config.verifier, payload, RecallVerdict)
                ok = (
                    not result_r.page_quote if result_r.verdict == "MISSING"
                    else bool(result_r.page_quote.strip()) and result_r.page_quote in page
                )
                row.update(result_r.model_dump(), status="completed", citation_ok=ok,
                           effective_verdict=result_r.verdict if ok else "MISSING",
                           redacted_citation="<REDACTED>" in result_r.page_quote)
                if ok and result_r.page_quote:
                    offset = page.index(result_r.page_quote)
                    line = page[:offset].count("\n") + 1
                    row["page_citation"] = {
                        "file": data["page_file"], "line": line, "text": page.splitlines()[line - 1],
                    }
            except StageError as exc:
                row["error"] = {"stage": exc.stage, "code": exc.code}
            row["calls"] = llm.calls[before:]
            recall.append(row)
        documents.append({
            "case_id": case_id, "page_provenance": data["case"]["page"],
            "extraction_errors": errors, "extracted_claims": len(claims),
            **metrics(precision[start_p:], recall[start_r:], len(claims), not errors),
            "strata": {
                severity: {
                    "extracted": sum(c.severity == severity for c in claims),
                    "selected": sum(c.severity == severity for c in chosen),
                    "verdicts": dict(Counter(r["effective_verdict"] for r in precision[start_p:]
                                             if r["severity"] == severity)),
                } for severity in ("critical", "normal")
            },
        })
    summary = {
        "schema_version": "1", "capture_sha256": capture["sha256"], "documents": documents,
        "overall": metrics(precision, recall, sum(d["extracted_claims"] for d in documents),
                           all(not d["extraction_errors"] for d in documents)),
        "aggregation": "micro; sampled claims, not a whole-page precision estimate",
        "semantic_gates_enabled": False, "promoted": False,
        "review_items": [
            {"case_id": row["case_id"], "target_id": row.get("claim_id", row.get("fact_id")),
             "status": row["status"], "citation_ok": row["citation_ok"],
             "verdict": row.get("verdict"), "effective_verdict": row["effective_verdict"]}
            for row in [*precision, *recall] if row["status"] != "completed" or not row["citation_ok"]
            or row.get("verdict") in {"CONTRADICTED", "NOT_VERIFIABLE", "WRONG", "MISSING"}
        ],
    }
    for name, rows in (("precision", precision), ("recall", recall)):
        safe_value(rows)
        path = output / (name + "_results.jsonl")
        with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    private_json(output / "calls.json", llm.calls)
    private_json(output / "precision_recall_summary.json", summary)
    return summary
