# 0014. Infrastructure scope: what `azd up` deploys vs. what is documented only

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0002](0002-workshop-format.md), [0012](0012-agent-identity-and-rbac.md), [0016](0016-state-and-audit-cosmos-db.md), [0018](0018-region-sweden-central.md), risks [R3](../risks.md#r3), [R4](../risks.md#r4)

> **Phasing (2026-10-08):** the scope below is unchanged, but delivery is phased by [ADR 0020](0020-manual-setup-first.md). The environment is set up **manually** per [docs/setup.md](../setup.md) during M0–M3, and codified as `azd` + Bicep in M4 ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).

## Context

Attendees must be able to deploy the pattern with `azd up` in their own subscription. Enterprise concerns such as landing zones, organisation-wide agent governance and capacity planning matter, but they vary by organisation and would make the repo hard to deploy.

## Decision

**In the repo (`azd up`, Bicep):**
- Microsoft Foundry resource + project
- Model deployments: **chat** model and **eval** model
- **Azure AI Search** (Foundry IQ)
- **Application Insights** (+ Log Analytics)
- **AI Gateway (API Management)**: token limits **per project + model deployment**, plus the **FinOps cost-attribution pattern** (tagged calls → APIM/App Insights logs) ([R4](../risks.md#r4))
- **Cosmos DB** (state & audit)
- **Agent identity RBAC**, applied as a **post-deploy step** ([R3](../risks.md#r3))

**Slides/docs only** ([next-steps](../next-steps.md)):
- Landing zone & subscription vending
- Agent 365
- Work IQ
- Advanced model deployment strategy (PTU, spillover, multi-region)

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Full landing zone in the repo | Organisation-specific and slow to deploy; it hides the agent pattern |
| Minimal deploy without gateway/Cosmos | Loses FinOps, limits and the audit story, which are core to the pattern |
| Per-agent token quotas at the gateway | Not supported natively; limits are per project + deployment ([R4](../risks.md#r4)) |

## Consequences

- **Positive:** a deployable, self-contained environment that demonstrates governance features.
- **Negative:** APIM adds deployment time and cost, and network isolation is not in v1.
- **Follow-ups:** M0 spike (R4); manual baseline in M1 ([#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5), [docs/setup.md](../setup.md)); `azd` + Bicep in M4 ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).
