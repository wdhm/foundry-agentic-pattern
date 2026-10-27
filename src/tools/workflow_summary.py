"""Source-free Actions explanations; never render model or source text."""

import argparse
import json
import os
from pathlib import Path


def overview(workflow: str, outcome: str) -> str:
    status = outcome if outcome in {"success", "failure", "cancelled", "skipped"} else "unknown"
    optimization = (
        "After a failed candidate, propose a bounded instruction revision; evaluate at most five candidates."
        if workflow == "loop"
        else "This preflight evaluates one hosted candidate; it does not optimize instructions."
    )
    rows = [
        "| Offline validation | Repository code and fixtures: tests, lint and types. "
        "Release also checks schemas and builds a local wheel. | No cloud inference; "
        "synthetic tests do not establish semantic quality. |",
        "| Approval and setup | Trusted main, explicit enable flag and protected environment; "
        "validate reviewed configuration before Azure login. | A skipped live job means not evaluated, not passed. "
        "A setup failure means no completed gate. |",
        "| Candidate inference | Run the selected cases against the isolated candidate. | "
        "Fresh model answers, not replayed passing fixtures. |",
        "| Structural and source validation | Check contracts, provenance, source isolation and evidence. | "
        "Valid structure and sources alone do not prove answer quality. |",
        "| Semantic judging | Judge groundedness and task adherence; tool-call accuracy only where applicable. | "
        "Required scores must meet the existing thresholds; missing scores cannot pass. |",
        f"| Instruction optimization | {optimization} | No unbounded retries or threshold relaxation. |",
        "| Decision | Read the runtime's completed gate result and coverage. | "
        "Partial coverage is not a full-suite pass. No automatic promotion or deployment. |",
    ]
    stages = "\n".join(rows)
    return f"""## How to read this evaluation

Offline job outcome: **{status}**. Offline success is not a model-quality pass.

| Stage | Inputs and action | What the result means |
|---|---|---|
{stages}

The live runtime performs its internal stages inside **one execution step**.
This table is a process map, not evidence that each stage ran or passed.
For the loop, one shared correction retry per case covers eligible schema/evidence repair;
that is distinct from instruction optimization. Existing deadlines, token limits,
schema rules and quality thresholds remain enforced.

**Reading the graph:** offline validation precedes the optional approved live job.
PRs never receive live credentials. The loop's push classifier keeps offline-only
quality changes offline; manual execution still requires all existing gates.
Release live execution additionally requires the manual cloud checkbox (default false).
If a job is skipped, inspect its condition and approval state, not the offline green check.
Summaries contain no source excerpts, prompts or model answers. Restricted diagnostics
remain separately approval-gated. Neither workflow publishes to wiki or Teams.
"""


def release_decision(path: Path) -> str:
    if not path.exists():
        return (
            "## Hosted gate decision\n\n"
            "No completed decision was written; not evaluated or interrupted. No promotion.\n"
        )
    decision = json.loads(path.read_text(encoding="utf-8"))
    statuses = {"blocked", "eligible_for_manual_review"}
    status = decision.get("status")
    label = status if isinstance(status, str) and status in statuses else "unrecognized decision (not a pass)"
    return (
        f"## Hosted gate decision\n\nOutcome: **{label}**.\n\n"
        "Eligibility is for manual review only, not promotion. No deployment, wiki or Teams publication.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("loop", "release"), required=True)
    parser.add_argument("--decision", type=Path)
    args = parser.parse_args()
    text = (
        release_decision(args.decision)
        if args.decision is not None
        else overview(args.workflow, os.environ.get("OFFLINE_OUTCOME", "unknown"))
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(text)


if __name__ == "__main__":
    main()
