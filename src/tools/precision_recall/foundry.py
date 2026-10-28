"""Approved publication of source-free projections; code scores are NOT new judge verdicts."""

import json
import math
import time
from pathlib import Path
from typing import Any

from tools.sandbox_eval import digest

from .calibration import rows
from .sources import private_json

CODE = (
    "def grade(sample: dict, item: dict) -> float:\n"
    "    return float(item['status'] == 'completed' and item['citation_ok'] "
    "and item['verdict'] in ('SUPPORTED', 'STATED'))\n"
)


def projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": digest(row["case_id"]), "target_id": digest(row.get("claim_id", row.get("fact_id", ""))),
        "verdict": row["effective_verdict"], "severity": row["severity"],
        "citation_ok": row["citation_ok"], "status": row["status"],
        "reason": "Precomputed local verdict; source-bearing reason retained in restricted local results.",
    }


def publish(project: Any, client: Any, run: Path, output: Path, run_id: str, deployment: str) -> None:
    """Catalog schema follows Microsoft Learn custom-evaluators (preview), not an invented REST API."""
    groups = {stage: [projection(r) for r in rows(run / (stage + "_results.jsonl"))]
              for stage in ("precision", "recall")}
    if any(not group for group in groups.values()):
        raise ValueError("Both nonempty result files are required for Foundry publication.")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    for stage, group in groups.items():
        name = f"precomputed-{stage}-{run_id}"
        evaluator = project.beta.evaluators.create_version(name=name, evaluator_version={
            "evaluator_type": "custom", "categories": ["quality"], "display_name": name,
            "description": "Code pass rate over precomputed verdicts; not independent judging or release gating.",
            "definition": {
                "type": "code", "code_text": CODE,
                "init_parameters": {
                    "type": "object", "properties": {
                        "deployment_name": {"type": "string"}, "pass_threshold": {"type": "number"},
                    }, "required": ["deployment_name", "pass_threshold"],
                },
                "metrics": {"result": {
                    "type": "continuous", "desirable_direction": "increase", "min_value": 0.0, "max_value": 1.0,
                }},
                "data_schema": {"type": "object", "required": ["item"], "properties": {
                    "item": {"type": "object", "properties": {
                        "verdict": {"type": "string"}, "status": {"type": "string"},
                        "citation_ok": {"type": "boolean"},
                    }, "required": ["verdict", "status", "citation_ok"]},
                }},
            },
        })
        private_json(output / f"{stage}-catalog.json", {"name": name, "version": evaluator.version})
        definition = client.evals.create(
            name=name, data_source_config={"type": "custom", "item_schema": {
                "type": "object", "properties": {
                    key: {"type": "boolean" if isinstance(value, bool) else "string"}
                    for key, value in group[0].items()
                }, "required": list(group[0]),
            }},
            testing_criteria=[{
                "type": "azure_ai_evaluator", "name": name, "evaluator_name": name,
                "initialization_parameters": {"deployment_name": deployment, "pass_threshold": 1.0},
            }],
        )
        remote = client.evals.runs.create(
            eval_id=definition.id, name=name,
            data_source={"type": "jsonl", "source": {"type": "file_content", "content": [{"item": r} for r in group]}},
        )
        private_json(output / f"{stage}-submitted.json", {
            "eval_id": definition.id, "run_id": remote.id, "status": remote.status,
            "meaning": "precomputed_code_pass_rate", "rows_sha256": digest(json.dumps(group, sort_keys=True)),
        })
        deadline = time.monotonic() + 300
        while remote.status in {"queued", "in_progress"} and time.monotonic() < deadline:
            time.sleep(5)
            remote = client.evals.runs.retrieve(eval_id=definition.id, run_id=remote.id)
        if remote.status != "completed" or remote.error:
            raise ValueError("Foundry code evaluation did not complete successfully; no pass claimed.")
        scored = list(client.evals.runs.output_items.list(eval_id=definition.id, run_id=remote.id))
        if len(scored) != len(group):
            raise ValueError("Foundry did not return every submitted result row.")
        values = []
        for item in scored:
            row = item.model_dump()
            results = row.get("results")
            if row.get("status") != "completed" or row.get("error") or not isinstance(results, list) or not results:
                raise ValueError("Foundry row did not complete code scoring.")
            for result in results:
                score = result.get("score")
                if (
                    result.get("error") or isinstance(score, bool) or not isinstance(score, (int, float))
                    or not math.isfinite(score) or score not in {0, 1}
                ):
                    raise ValueError("Foundry code score is missing or invalid.")
                values.append(score)
        private_json(output / f"{stage}-completed.json", {
            "eval_id": definition.id, "run_id": remote.id, "status": remote.status,
            "rows": len(scored), "report_url": remote.report_url,
            "meaning": "precomputed_code_pass_rate_not_new_judging",
            "code_scores": values,
        })
