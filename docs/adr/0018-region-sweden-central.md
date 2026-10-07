# 0018. Region: Sweden Central

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0009](0009-hosted-agent-runtime.md), [0014](0014-infrastructure-scope.md), risk [R2](../risks.md#r2)

## Context

The primary audience operates under EU data-residency expectations. The region must support Foundry hosted agents, the required models, Azure AI Search, API Management and Cosmos DB.

## Decision

- The default region is **Sweden Central**, configured as the default `azd` location.
- Hosted agent availability in Sweden Central is verified ([R2](../risks.md#r2)).
- The region remains a parameter, so forks can choose another region.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| East US / other US regions | Broadest feature availability, but conflicts with EU data-residency expectations |
| West Europe | Capacity constraints are common for new AI features |

## Consequences

- **Positive:** an EU region with hosted agent support.
- **Negative:** individual model versions or preview features may arrive later than in US regions. Check them during M1.
