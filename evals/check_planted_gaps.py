"""Check an agent result against a planted-gap scenario.

Standard library only. Reports gap recall and evidence integrity, which are the
MVP versions of the eval-gate metrics in evals/README.md.

    python evals/check_planted_gaps.py --invoke              # run the agent, then check
    python evals/check_planted_gaps.py --result result.json  # check a saved result
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_SCENARIO = Path(__file__).parent / "datasets" / "order-sync-retry.json"
DEFAULT_ENDPOINT = "https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic"


def invoke_agent(endpoint: str, agent: str, prompt: str) -> dict:
    az = shutil.which("az") or "az"
    token = subprocess.run(
        [
            az,
            "account",
            "get-access-token",
            "--resource",
            "https://ai.azure.com",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    body = json.dumps({"input": prompt, "agent_reference": {"name": agent, "type": "agent_reference"}}).encode()
    request = urllib.request.Request(
        f"{endpoint}/openai/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Foundry-Features": "AgentEndpoints=V1Preview",
        },
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        raw = json.load(response)
    tool_calls = [
        f"{item.get('server_label')}.{item.get('name')}"
        for item in raw.get("output", [])
        if item.get("type") == "mcp_call"
    ]
    print("Tool calls:", ", ".join(tool_calls) or "none")
    text = "".join(
        part.get("text", "")
        for item in raw.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
    )
    return json.loads(text)


def text_of(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(text_of(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(text_of(v) for v in value)
    return str(value)


def check(scenario: dict, result: dict) -> dict:
    claims = [text_of(item).lower() for item in result.get("findings", []) + result.get("proposed_changes", [])]
    gaps = []
    for gap in scenario["planted_gaps"]:
        found = any(all(any(term in claim for term in group) for group in gap["match_all"]) for claim in claims)
        gaps.append({"id": gap["id"], "title": gap["title"], "found": found})

    evidence = {item.get("id"): item for item in result.get("evidence", [])}
    referenced = {
        ref
        for item in result.get("findings", []) + result.get("proposed_changes", [])
        for ref in item.get("evidence_refs", [])
    }
    problems = [f"reference {ref} has no evidence entry" for ref in sorted(referenced - evidence.keys())]
    allowed_git = set(scenario["expected_evidence"]["git_versions"])
    for item in evidence.values():
        if item.get("source") == "git" and item.get("version") not in allowed_git:
            problems.append(f"evidence {item.get('id')} cites git version {item.get('version')!r}, not the PR head")
        if not item.get("version"):
            problems.append(f"evidence {item.get('id')} has no version")
    sources = {item.get("source") for item in evidence.values()}
    missing_sources = [s for s in scenario["expected_evidence"]["required_sources"] if s not in sources]

    return {
        "status_ok": result.get("documentation_status") == scenario["expected_status"],
        "gaps": gaps,
        "recall": sum(g["found"] for g in gaps) / len(gaps),
        "evidence_problems": problems,
        "missing_sources": missing_sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--result", type=Path, help="Saved agent result (JSON)")
    source.add_argument("--invoke", action="store_true", help="Invoke the agent with the scenario prompt")
    parser.add_argument("--endpoint", default=os.environ.get("FOUNDRY_PROJECT_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--save", type=Path, help="Write the agent result to this file")
    parser.add_argument("--min-recall", type=float, default=1.0)
    args = parser.parse_args()

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    if args.invoke:
        result = invoke_agent(args.endpoint, scenario["agent"], scenario["prompt"])
    else:
        result = json.loads(args.result.read_text(encoding="utf-8"))
    if args.save:
        args.save.write_text(json.dumps(result, indent=2), encoding="utf-8")

    report = check(scenario, result)
    print(f"Scenario: {scenario['scenario']}")
    status_note = "ok" if report["status_ok"] else f"expected {scenario['expected_status']}"
    print(f"Status {result.get('documentation_status')!r}: {status_note}")
    for gap in report["gaps"]:
        print(f"  [{'x' if gap['found'] else ' '}] {gap['id']} {gap['title']}")
    print(f"Gap recall: {report['recall']:.0%}")
    for problem in report["evidence_problems"]:
        print(f"  Evidence problem: {problem}")
    for source_name in report["missing_sources"]:
        print(f"  Missing evidence source: {source_name}")

    passed = (
        report["status_ok"]
        and report["recall"] >= args.min_recall
        and not report["evidence_problems"]
        and not report["missing_sources"]
    )
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
