# 0009. Runtime: Foundry hosted agent (container) with Microsoft Agent Framework

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0008](0008-human-in-the-loop-approval.md), [0010](0010-python-and-pydantic-contracts.md), [0015](0015-registry-foundry-fleet-management.md), risks [R1](../risks.md#r1), [R2](../risks.md#r2)

## Context

The agent has to enforce approval on tool calls, validate a typed contract, persist state, emit custom telemetry and run deterministic logic around the model. It should still be managed, versioned and published by the platform.

## Decision

- The Documentation Agent runs as a **Microsoft Foundry hosted agent** (a container managed by Foundry).
- It is built with the **Microsoft Agent Framework** (Python).
- Versions, endpoints and publishing are handled by Foundry ([0015](0015-registry-foundry-fleet-management.md)). Rollback and canary use the endpoint `version_selector` ([R2](../risks.md#r2)).

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **Declarative prompt agent** (Foundry) | Zero code, fastest to start | Cannot implement the approval interrupt ([R1](../risks.md#r1)), contract validation or custom audit, and is limited for deterministic steps |
| Self-hosted container (Container Apps/AKS) | Full control | Loses Foundry fleet management, publishing and versioning, and means more ops |
| Other agent frameworks | Familiar to some teams | Less integrated with Foundry hosting and telemetry |

## Consequences

- **Positive:** full control over the runtime logic, with platform-managed lifecycle, identity and publishing.
- **Negative:** container build pipeline required. Hosted agents need to be available in the target region (verified for Sweden Central, [R2](../risks.md#r2)).
- **Follow-ups:** stub hosted agent in M1.
