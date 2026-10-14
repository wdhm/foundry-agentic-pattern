# evals/

Evaluation sets, metrics and the **CI eval gate** ([ADR 0013](../docs/adr/0013-evaluation-gate-in-ci.md)).

> MVP: one hand-made scenario and a checker ([ADR 0022](../docs/adr/0022-mvp-scope-platform-first.md)). The full gate in GitHub Actions comes in M2.

## MVP: planted-gap scenario

| File | What |
|---|---|
| [`datasets/order-sync-retry.json`](datasets/order-sync-retry.json) | Ground truth for demo [PR #62](https://github.com/wdhm/foundry-agentic-pattern/pull/62): the prompt, the subject at the PR head SHA, three planted gaps (retry/backoff, `erp.timeoutSeconds`, dead-letter queue) with their `DS-xx` rules, and the allowed evidence versions |
| [`check_planted_gaps.py`](check_planted_gaps.py) | Standard-library checker: documentation status, **gap recall** and **evidence integrity** (every reference resolves, git evidence is at the PR head SHA, git and wiki sources present) |

```powershell
az login
python evals/check_planted_gaps.py --invoke                 # run doc-agent-spike, then check
python evals/check_planted_gaps.py --result my-result.json  # check a saved result
```

A gap counts as found when one finding or proposed change contains a term from every `match_all` group. The script exits 1 on failure, so it can be used as a CI step later. Verified 2026-10-14 against `doc-agent-spike:6`: 3/3 gaps, no evidence problems, `PASS`.

## Gate (blocking)

| Metric | Threshold |
|---|---|
| `AgentResult` schema validity | **100 %** |
| Gap recall on planted gaps | **≥ target** (initial target set in M2) |
| Fabricated evidence references | **0** |
| Correct "Information missing" behaviour on scenarios with no source | **100 %** |

## Reported (non-blocking)
Built-in Foundry evaluators: **groundedness**, **tool call accuracy** and **task adherence**. Trends are tracked per agent version.

## Behaviour
- The gate runs in GitHub Actions for every agent change.
- **Gate fail → no promote.** The endpoint `version_selector` keeps traffic on the last good version, which works as an automatic rollback ([R2](../docs/risks.md#r2)).

## Planned layout
```text
evals/
├── datasets/       # Scenarios: AgentRequest + expected findings (ground truth)
├── metrics/        # Custom evaluators (recall, fabricated refs, info-missing)
└── gate.py         # Aggregates results and enforces thresholds
```

**Owner:** P3 (AgentOps & platform): Louise ([@llandinl](https://github.com/llandinl))
