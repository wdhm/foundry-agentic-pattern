# evals/

Evaluation sets, metrics and the **CI eval gate** ([ADR 0013](../docs/adr/0013-evaluation-gate-in-ci.md)).

> Placeholder. Implementation starts in **M2**.

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
