# 0020. Manual Azure setup first, infrastructure as code later

- **Status:** Accepted
- **Date:** 2026-10-08
- **Deciders:** John ([@johnsward](https://github.com/johnsward)), Rickard ([@wdhm](https://github.com/wdhm)), Louise ([@llandinl](https://github.com/llandinl))
- **Related:** amends the phasing of [0014](0014-infrastructure-scope.md); [0002](0002-workshop-format.md), [0018](0018-region-sweden-central.md), [setup runbook](../setup.md), [#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5), [#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)

## Context

[ADR 0014](0014-infrastructure-scope.md) defines *what* the environment contains, and assumed it would be deployed with `azd up` from M1. However, the M0 spikes (R1–R4) can still change the design: the identity model, the Toolbox connections, AI Gateway placement and publishing to Teams. Writing Bicep before those answers are in would mean rewriting it, and it would slow down the spikes and the walking skeleton.

## Decision

- We will **set up Azure manually** (portal / CLI) for M0–M3, in one **shared environment** in Sweden Central.
- Every manual step is recorded in a **runbook**, [docs/setup.md](../setup.md), owned by P3 ([#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5)). If it isn't in the runbook, it doesn't exist.
- The **scope** in [ADR 0014](0014-infrastructure-scope.md) is unchanged. Only the delivery method is phased.
- **IaC (`azd` + Bicep)** is added in **M4** by codifying the runbook ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)), so the workshop take-away (`azd up`) still holds.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| `azd` + Bicep from M1 (original plan) | Reproducible from day one | Rework while the spikes are still changing the design; slower start | Too early: the design isn't stable yet |
| Manual setup, no IaC at all | Fastest | Attendees can't run `azd up`; breaks [ADR 0002](0002-workshop-format.md) | The repo must be deployable on its own |

## Consequences

- **Positive:** all three tracks can start immediately; spikes iterate directly in the portal.
- **Negative / trade-offs:** the environment isn't reproducible until M4, so configuration drift is possible. The runbook is the mitigation.
- **Follow-ups:** keep [docs/setup.md](../setup.md) current; codify it in [#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52), and verify it with a clean `azd up` in the dry run ([#40](https://github.com/wdhm/foundry-agentic-pattern/issues/40)).
