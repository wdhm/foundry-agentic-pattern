# 0013. Ground-truth eval gate in CI; Foundry evaluators reported but non-blocking

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0004](0004-documentation-agent-story.md), [0005](0005-generic-repo-with-fictional-data.md), [0010](0010-python-and-pydantic-contracts.md), risk [R2](../risks.md#r2)

## Context

Agent behaviour changes whenever the prompt, model, tools or code changes. Without an automated quality gate, regressions such as fabricated evidence would reach reviewers. LLM-judged metrics are useful for trends, but too noisy to block releases on their own.

## Decision

A **ground-truth-based eval gate** runs in GitHub Actions for every new agent version.

**Blocking metrics**

| Metric | Threshold |
|---|---|
| `AgentResult` schema validity | **100 %** |
| Gap recall on planted gaps | **≥ target** (set in M2) |
| Fabricated evidence references | **0** |
| Correct "Information missing" behaviour | **100 %** on scenarios with no supporting source |

**Reported, non-blocking:** the built-in Foundry evaluators **groundedness**, **tool call accuracy** and **task adherence**.

**Gate fail → no promote.** Traffic stays on the previous version through the endpoint `version_selector` ([R2](../risks.md#r2)), which makes it an automatic rollback.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| LLM-as-judge metrics as blocking | Non-deterministic, so the gate would be flaky |
| Manual QA before release | Doesn't scale and is not repeatable |
| No gate; monitor in production | Regressions would reach reviewers first |

## Consequences

- **Positive:** objective, repeatable quality bar, and a demonstrable "bad version is blocked" moment.
- **Negative:** ground truth must be maintained as the sample data evolves.
- **Follow-ups:** eval datasets and metrics (M2, P3 with P2 data). The recall target is set after a baseline run.
