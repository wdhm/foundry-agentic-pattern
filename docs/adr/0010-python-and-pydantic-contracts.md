# 0010. Python; Pydantic models are the single source of truth for AgentRequest/AgentResult

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0004](0004-documentation-agent-story.md), [0006](0006-sources-and-trigger.md), [0013](0013-evaluation-gate-in-ci.md)

## Context

The contract is consumed by the agent, by trigger adapters (GitHub Actions, CLI), by the Teams rendering and by the evaluators. If it were defined in several places it would drift. Schema validity is also a blocking eval metric.

## Decision

- The implementation language is **Python**.
- **Pydantic models** for `AgentRequest` and `AgentResult` (in `src/contracts/`) are the **single source of truth**.
- **JSON Schema is generated** from the models, committed, and checked for drift in CI.
- The contract carries an explicit **`contract_version`**. Breaking changes bump it and require an ADR.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| JSON Schema first, generate models | Weaker developer ergonomics in Python; validation logic ends up split |
| OpenAPI spec | Built for HTTP APIs; the agent contract is message-oriented |
| TypeScript / .NET | Python has the richest Agent Framework and evaluation ecosystem and is the most familiar to the audience |

## Consequences

- **Positive:** one definition with typed validation everywhere, and a schema that non-Python consumers can use.
- **Negative:** schema evolution must be managed carefully (versioning and compatibility tests).
- **Follow-ups:** contract package and schema generation in M1.
