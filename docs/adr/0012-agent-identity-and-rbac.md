# 0012. Identity: agent's own identity (Entra Agent ID), least privilege per source; OBO as alternative

- **Status:** Accepted; Azure DevOps access refined by [0021](0021-agent-user-and-ado-mcp-gateway.md) (spike [R3](../risks.md#r3) done)
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0008](0008-human-in-the-loop-approval.md), [0011](0011-knowledge-foundry-iq-and-toolbox.md), [0014](0014-infrastructure-scope.md), risk [R3](../risks.md#r3)

## Context

The agent runs from CI with no interactive user present, reads from several sources and writes (gated) to the wiki. Its access must be auditable and minimal. Shared service accounts and stored secrets are unacceptable.

## Decision

- The agent uses **its own identity**: **Entra Agent ID**, which is assigned to the hosted agent.
- **Least privilege per source:** read-only on GitHub, work items, AI Search and models. Its Cosmos DB access is limited to the agent database.
- The **wiki write** is possible **only through the approval-gated tool** ([0008](0008-human-in-the-loop-approval.md)).
- The **approver** is recorded in the audit record and in the **wiki commit message**.
- **Role assignments for the agent identity run as a post-deploy CI step.** The identity exists only after the agent is created, and **publishing creates a new agent identity** ([R3](../risks.md#r3)).
- **Fallback** if Azure DevOps does not accept agent-identity service principals: authenticate the Toolbox connection with the **project managed identity** or a **user-assigned managed identity** ([R3](../risks.md#r3)).

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **On-behalf-of (OBO)** the requesting user | Per-user permissions, natural for interactive use | No user in CI-triggered runs; complex token flow through Teams and CI |
| Project managed identity for everything | Simple, exists at deploy time | Shared across agents in the project, so a coarser audit |
| Service principal + secret | Familiar | Secret management and rotation; against the guidance |

## Consequences

- **Positive:** per-agent auditability and minimal blast radius, with no secrets.
- **Negative:** identity lifecycle complexity (new identity on publish). Azure DevOps support for agent identities is unverified.
- **Follow-ups:** M0 spike (R3) and the post-deploy RBAC workflow (M2).
