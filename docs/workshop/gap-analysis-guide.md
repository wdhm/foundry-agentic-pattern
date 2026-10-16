# Gap analysis: five-minute demonstration (#13)

> **Transition note (2026-10-16):** P1 has selected the hosted app as the main
> runtime ([ADR 0024](../adr/0024-hosted-documentation-runtime.md)). This guide
> records the working prompt-agent reference. Its passing results do not yet
> demonstrate the hosted implementation; #13 remains incomplete on that path.
> P1's local hosted implementation and P2 handoff are documented in the
> [hosted README](../../src/agents/documentation-agent/README.md).

**Target:** `doc-agent` prompt agent in the existing `proj-agentic` project.
This is separate from the `documentation-agent` hosted stub.

## What to show

1. Show [demo PR #62](https://github.com/wdhm/foundry-agentic-pattern/pull/62)
   and the sparse wiki page `/Order Sync/Overview`. Keep the demo PR open.
2. Run the planted-gaps scenario. Point out retry/backoff, the ERP timeout and
   dead-letter configuration in the findings.
3. Run the information-missing scenario. It must not invent a business owner,
   data classification or operational links.
4. Show the Foundry tool trace: knowledge retrieval, GitHub file reads, wiki
   and work-item reads. Evidence is tied to those actual reads.

## Run

From the repository root, sign in with the team Azure CLI account and install
the shared contracts. Commands below target the verified **version 3**:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[prompt,dev]"
New-Item -ItemType Directory -Force evals\results\gap-analysis | Out-Null

.\.venv\Scripts\python.exe evals\check_planted_gaps.py --invoke --agent-version 3 `
  --scenario evals\datasets\order-sync-retry.json `
  --save evals\results\gap-analysis\retry.json `
  --save-response evals\results\gap-analysis\retry-response.json

.\.venv\Scripts\python.exe evals\check_planted_gaps.py --invoke --agent-version 3 `
  --scenario evals\datasets\order-sync-information-missing.json `
  --save evals\results\gap-analysis\missing.json `
  --save-response evals\results\gap-analysis\missing-response.json
```

These are real model/tool calls and incur usage charges. The response files can
contain source content: keep them in ignored `evals/results/`, not in commits.
Review saved evidence without another model call:

```powershell
.\.venv\Scripts\python.exe evals\check_planted_gaps.py `
  --response evals\results\gap-analysis\retry-response.json
```

## Observed result (2026-10-16)

| Version / scenario | Result |
|---|---|
| `doc-agent:2`, change review | Found all three gaps but incorrectly expanded into a production audit and returned `insufficient_information` |
| `doc-agent:2`, missing facts | Passed the scenario; some excerpts were paraphrases rather than source quotes |
| `doc-agent:3`, change review | PASS: `gaps_found`, 3/3 planted gaps, valid schema, no unmatched evidence URI/version/excerpt |
| `doc-agent:3`, missing facts | PASS: `insufficient_information`, 3/3 missing facts, valid schema, no unmatched evidence URI/version/excerpt or forbidden invented proposal values |

Version 3 tightens scope and asks for short verbatim source quotes. The saved
responses were rechecked offline; there were no wiki write calls or approval
submissions. These observations cover these two runs, not a guarantee across
all future inputs or model runs.

## What the checker establishes

It validates contract v1 with Pydantic, compares the scenario's expected status
and recall (default 100%), checks required sources and pinned Git SHAs, and
rejects incomplete/error/approval responses.

For `--invoke` and `--response`, it also requires Foundry IQ retrieval and
matches each evidence URI, version and excerpt to the successful read-tool
output. It supports the current MVP Git file, wiki page and work-item formats.
Work-item API and browser links are treated as equivalent only for the same
organization/project/item. Quoted and unquoted wiki ETags identify the same version.
Directory listings and PR summaries are not accepted as file evidence. Unsupported
formats fail to match, rather than passing unverified. Verbatim matching normalizes
whitespace and HTML entities; it does not judge every semantic claim in a proposal.
This is an evidence-integrity check, not a general groundedness evaluator.

`--result` alone cannot establish that sources were actually read; it explicitly
reports this limitation. The scenario's existing regex guard detects selected
invented values, not every possible hallucination.

## Configuration and references

The [versioned prompt and policy](../../src/agents/documentation-agent/README.md)
are shared with the hosted implementation. For this prompt-agent reference,
Foundry orchestrates the existing tools. For the hosted path, Agent Framework
in the Python app runs the model/tool loop. No new infrastructure, Cosmos store
or CI pipeline is introduced by the local P1 work.

[Foundry prompt agents](https://learn.microsoft.com/azure/foundry/agents/quickstarts/prompt-agent)
· [MCP tools](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol)
· [P2 evidence-version guide](information-missing-guide.md#evidence-at-exact-versions-how-to-resolve-them)
