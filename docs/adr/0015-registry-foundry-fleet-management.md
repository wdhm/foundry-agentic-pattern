# 0015. Registry: Foundry fleet management, no custom registry

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0009](0009-hosted-agent-runtime.md), [0013](0013-evaluation-gate-in-ci.md)

## Context

A pattern for *many* agents needs an inventory: which agents exist, which versions, which endpoints, who owns them, and what is live. Building a custom registry is a common anti-pattern because it duplicates platform capabilities and drifts from reality.

## Decision

- **Foundry fleet management** is the agent registry: inventory, versions, endpoints and traffic routing.
- No custom registry database or service is built.
- Ownership and metadata (owner, contract version, policy version) are stored as agent metadata/tags, and in the audit record ([0016](0016-state-and-audit-cosmos-db.md)).

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Custom registry (Cosmos/SQL + API) | Duplicates the platform and drifts from the deployed reality |
| Git-only registry (YAML catalogue) | Useful as documentation, but does not reflect runtime state |

## Consequences

- **Positive:** the registry matches the deployed reality, with less to build.
- **Negative:** organisation-wide governance across M365 needs Agent 365 ([next-steps](../next-steps.md#3-agent-365)).
