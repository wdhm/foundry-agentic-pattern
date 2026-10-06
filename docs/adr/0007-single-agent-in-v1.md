# 0007. One agent in v1; Agent-to-Agent documented as next step

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0008](0008-human-in-the-loop-approval.md), [0012](0012-agent-identity-and-rbac.md), [next-steps](../next-steps.md#1-agent-to-agent-a2a-separate-publisher-agent)

## Context

Multi-agent architectures (for example an Analyst agent plus a Publisher agent with a separate write identity) improve separation of duties. They also add identities, contracts, tracing across agents and failure modes. v1 has to be explainable in a half day and deployable with `azd up`.

## Decision

- v1 ships **exactly one agent**: the Documentation Agent.
- The wiki write is protected by an **approval-gated tool** ([0008](0008-human-in-the-loop-approval.md)) instead of a separate agent.
- **Agent-to-Agent** (for example a **Publisher agent with its own write identity**) is **documented as the next step only**.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Analyst + Publisher agents in v1 | Doubles identity/RBAC setup and complicates tracing and evals, without adding much to the core story |
| Orchestrator + specialist sub-agents | Over-engineered for a single, well-scoped task |

## Consequences

- **Positive:** simpler build, demo and evals.
- **Negative:** one identity has read access and (gated) write access. Approval gating and audit mitigate this.
- **Follow-ups:** A2A design notes are in [next-steps](../next-steps.md).
