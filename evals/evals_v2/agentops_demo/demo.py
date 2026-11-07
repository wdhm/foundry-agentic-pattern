"""Offline-only AgentOps story: synthetic evidence, real comparisons, no deployment."""

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path

HERE = Path(__file__).parent
SCENARIOS = ("passing-release", "blocked-by-groundedness")
METRICS = {
    "wiki-claims": (0, 1, 0.9),
    "wiki-accuracy": (0, 1, 0.9),
    "groundedness": (1, 5, 4),
    "task-adherence": (0, 1, 1),
    "tool-call-accuracy": (1, 5, 4),
}
CASES = (
    "wiki-answer-supported",
    "wiki-information-missing",
    "wiki-conflicting-sources",
    "tool-retry",
    "tool-unavailable",
)
JOBS = {metric: "eval_" + metric.replace("-", "_") for metric in METRICS}
MOCK = {
    "candidate_version": "v21",
    "previous_serving_version": "v13",
    "instructions_revision": "demo-prompt-r7",
    "runtime_configuration": {"revision": "demo-runtime-r3", "temperature": 0, "tools": "synthetic-only"},
    "model": {
        "deployment": "mock-model-deployment",
        "name": "mock-language-model",
        "version": "demo-model-2026-01",
        "upgrade_policy": "mock-no-auto-upgrade",
    },
    "dataset_revision": "demo-dataset-r1",
    "evaluator_configuration_revision": "demo-evaluators-r1",
    "evaluator_model_version": "mock-judge-2026-01",
}


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def manifest(scenario, sha, run_id, attempt, repository):
    if not all(isinstance(value, str) for value in (scenario, sha, run_id, attempt, repository)):
        raise ValueError("Scenario and actual GitHub metadata must be strings.")
    if scenario not in SCENARIOS or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid scenario or Git commit SHA.")
    if not run_id.isdecimal() or not attempt.isdecimal() or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Invalid GitHub run metadata.")
    image_digest = hashlib.sha256(f"MOCK:{sha}".encode()).hexdigest()
    return {
        "label": "DEMO / MOCK — no external resources changed",
        "scenario": scenario,
        "actual_github_metadata": {
            "source_sha": sha,
            "run_id": run_id,
            "run_attempt": attempt,
            "repository": repository,
        },
        "simulated_release": {**MOCK, "image": f"mock.invalid/agentops/wiki@sha256:{image_digest}"},
    }


def validate_manifest(value):
    if not isinstance(value, dict) or not isinstance(value.get("actual_github_metadata"), dict):
        raise ValueError("Missing or malformed release manifest.")
    actual = value["actual_github_metadata"]
    expected = manifest(
        value["scenario"], actual["source_sha"], actual["run_id"], actual["run_attempt"], actual["repository"]
    )
    if json.dumps(value, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError("Manifest is incomplete or differs from the DEMO release contract.")
    if "GITHUB_RUN_ID" in os.environ:
        for field, env in (
            ("source_sha", "GITHUB_SHA"),
            ("run_id", "GITHUB_RUN_ID"),
            ("run_attempt", "GITHUB_RUN_ATTEMPT"),
            ("repository", "GITHUB_REPOSITORY"),
        ):
            if actual[field] != os.environ[env]:
                raise ValueError(f"Manifest does not belong to this GitHub run: {field}")
        if value["scenario"] != os.environ["DEMO_SCENARIO"]:
            raise ValueError("Manifest does not match the selected scenario.")
    return value


def fixture(scenario):
    rows = read(HERE / "fixtures.json")[scenario]
    if set(rows) != set(CASES):
        raise ValueError("Fixture must include every synthetic case.")
    for case, scores in rows.items():
        if set(scores) != set(METRICS):
            raise ValueError(f"Incomplete metrics: {case}")
        for metric, score in scores.items():
            applicable = metric == "task-adherence" or (
                case.startswith("tool-") if metric == "tool-call-accuracy" else case.startswith("wiki-")
            )
            if not applicable:
                if score is not None:
                    raise ValueError(f"Expected intentional N/A: {case}/{metric}")
            else:
                low, high, _ = METRICS[metric]
                if type(score) not in (int, float) or not math.isfinite(score) or not low <= score <= high:
                    raise ValueError(f"Invalid applicable score: {case}/{metric}")
    return rows


def evidence(release, metric):
    validate_manifest(release)
    rows = fixture(release["scenario"])
    cases = {case: rows[case][metric] for case in CASES}
    applicable = [value for value in cases.values() if value is not None]
    score = sum(applicable) / len(applicable)
    low, high, threshold = METRICS[metric]
    return {
        "label": "DEMO / MOCK evaluation",
        "manifest_sha256": hashlib.sha256(json.dumps(release, sort_keys=True).encode()).hexdigest(),
        "candidate_version": release["simulated_release"]["candidate_version"],
        "metric": metric,
        "scale": [low, high],
        "threshold": threshold,
        "cases": cases,
        "score": score,
        "passed": score >= threshold,
    }


def collect(release, directory, outcomes):
    if not isinstance(outcomes, dict) or any(not isinstance(outcome, dict) for outcome in outcomes.values()):
        raise ValueError("Malformed upstream job outcomes.")
    errors, results = [], {}
    for metric in METRICS:
        try:
            value = read(directory / f"{metric}.json")
            expected = evidence(release, metric)
            # Compare serialized JSON too: True must not impersonate a numeric 1.
            if json.dumps(value, sort_keys=True) != json.dumps(expected, sort_keys=True):
                raise ValueError("Malformed, incomplete, or mismatched evidence.")
            results[metric] = value
            if not value["passed"]:
                errors.append(f"{metric}: {value['score']:.3f} < required {value['threshold']:g}")
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(f"{metric}: invalid or missing evidence ({error})")
        if outcomes.get(JOBS[metric], {}).get("result") != "success":
            errors.append(f"{metric}: upstream evaluation job did not succeed")
    return results, errors


def version_table(release):
    mock, actual = release["simulated_release"], release["actual_github_metadata"]
    return [
        "## Release-version manifest",
        "| Kind | Field | Value |",
        "|---|---|---|",
        *[f"| ACTUAL GitHub | {key} | `{value}` |" for key, value in actual.items()],
        *[
            f"| MOCK | {key} | `{json.dumps(value, sort_keys=True) if isinstance(value, dict) else value}` |"
            for key, value in mock.items()
        ],
        "",
        "Pinning an agent version does not freeze an independently managed model deployment. "
        "The recorded model version is release evidence, not a model-version lock.",
        "",
    ]


DISCLAIMER = "Simulation only. No models called or external resources changed."


def summary(release, results, errors):
    mock = release["simulated_release"]
    eligible = not errors
    text = [
        "# AgentOps release decision",
        "",
        DISCLAIMER,
        "",
        f"**Candidate:** {mock['candidate_version']}  ",
        f"**Previous serving version:** {mock['previous_serving_version']}  ",
        f"**Scenario:** {release['scenario']}  ",
        "**Decision:** " + ("ELIGIBLE FOR SIMULATED RELEASE" if eligible else "BLOCKED"),
        "",
        *version_table(release),
        "## Evaluation overview",
        "| DEMO metric | DEMO scale | Mean score | Threshold (>=) | Status |",
        "|---|---|---|---|---|",
    ]
    for metric, (low, high, threshold) in METRICS.items():
        result = results.get(metric)
        score = f"{result['score']:.3f}" if result else "INVALID / MISSING"
        status = ("PASS" if result["passed"] else "FAIL") if result else "BLOCKED"
        text.append(f"| {metric} | {low}–{high} | {score} | {threshold:g} | {status} |")
    text += [
        "",
        "## Synthetic test cases",
        "| Case | " + " | ".join(METRICS) + " |",
        "|---|" + "---|" * len(METRICS),
    ]
    for case in CASES:
        cells = []
        for metric in METRICS:
            if metric not in results:
                cells.append("INVALID / MISSING")
            else:
                value = results[metric]["cases"][case]
                cells.append("N/A" if value is None else str(value))
        text.append(f"| {case} | " + " | ".join(cells) + " |")
    text += [
        "",
        "Aggregation: arithmetic mean of applicable cases per metric; each metric must meet its threshold. "
        "N/A is intentional: Wiki metrics apply only to Wiki cases, tool-call accuracy only to tool cases, "
        "and task adherence to all cases. Missing applicable scores block release. "
        "These scales are DEMO conventions, not universal Foundry evaluator scales.",
        "",
    ]
    if errors:
        text += ["## Why release is blocked", *[f"- {error}" for error in errors], ""]
        text += [f"**Mock serving version remains {mock['previous_serving_version']}.** No release was performed."]
    else:
        text += ["The evaluated candidate is eligible for release; not yet promoted."]
    return "\n".join(text) + "\n"


def publish(text, output, filename="summary.md"):
    (output / filename).write_text(text, encoding="utf-8")
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(text)


def set_output(key, value):
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("manifest", "simulate", "evaluate", "gate", "promote"))
    parser.add_argument("--scenario", choices=SCENARIOS)
    parser.add_argument("--metric", choices=METRICS)
    parser.add_argument("--stage", choices=("staging", "smoke"))
    parser.add_argument("--evidence", type=Path, default=Path("evidence"))
    parser.add_argument("--output", type=Path, default=Path("demo-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.command == "gate":
        set_output("eligible", "false")
    try:
        if args.command == "manifest":
            release = manifest(
                args.scenario,
                os.environ["GITHUB_SHA"],
                os.environ["GITHUB_RUN_ID"],
                os.environ["GITHUB_RUN_ATTEMPT"],
                os.environ["GITHUB_REPOSITORY"],
            )
            write(args.output / "release-manifest.json", release)
            publish(
                "\n".join(["# Build", "", f"**Scenario:** {release['scenario']}", "", *version_table(release)]),
                args.output,
                filename="build-summary.md",
            )
            return 0
        release = validate_manifest(read(args.evidence / "release-manifest.json"))
        if args.command == "evaluate":
            if not args.metric:
                raise ValueError("--metric is required")
            result = evidence(release, args.metric)
            write(args.output / f"{args.metric}.json", result)
            publish(
                f"# {args.metric}\n\nCandidate: {result['candidate_version']}\n\n"
                f"Score: {result['score']:.3f}; threshold: >= {result['threshold']}; "
                f"result: {'PASS' if result['passed'] else 'FAIL'}.\n",
                args.output,
                filename=f"{args.metric}-summary.md",
            )
            return 0 if result["passed"] else 1
        if args.command == "gate":
            results, errors = collect(release, args.evidence, json.loads(os.environ["NEEDS_JSON"]))
            write(args.output / "decision.json", {"eligible": not errors, "errors": errors, "manifest": release})
            publish(summary(release, results, errors), args.output)
            set_output("eligible", str(not errors).lower())
            return 1 if errors else 0
        if args.command == "simulate":
            if not args.stage:
                raise ValueError("--stage is required")
            publish(
                f"# {'Deploy to staging' if args.stage == 'staging' else 'Smoke tests'}\n\n"
                f"Candidate: {release['simulated_release']['candidate_version']}\n\nStatus: passed.\n",
                args.output,
            )
            return 0
        decision = read(args.evidence / "decision.json")
        expected_decision = {"eligible": True, "errors": [], "manifest": release}
        if json.dumps(decision, sort_keys=True) != json.dumps(expected_decision, sort_keys=True):
            raise ValueError("No matching successful quality-gate decision.")
        results, errors = collect(release, args.evidence, {job: {"result": "success"} for job in JOBS.values()})
        if errors:
            raise ValueError(f"Promotion evidence invalid: {errors}")
        mock = release["simulated_release"]
        write(
            args.output / "mock-serving.json",
            {
                "label": "DEMO / MOCK",
                "previous": mock["previous_serving_version"],
                "serving": mock["candidate_version"],
                "manifest": release,
            },
        )
        publish(
            "# Promotion complete\n\n"
            f"Mock serving version changed from **{mock['previous_serving_version']}** to the evaluated "
            f"candidate **{mock['candidate_version']}**, using the same image and manifest.\n",
            args.output,
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        publish(
            "# AgentOps — BLOCKED\n\n"
            f"Invalid or missing evidence: {error}\n\n"
            "Mock serving version remains v13.\n" + (f"\n{DISCLAIMER}\n" if args.command == "gate" else ""),
            args.output,
        )
        print(f"BLOCKED: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
