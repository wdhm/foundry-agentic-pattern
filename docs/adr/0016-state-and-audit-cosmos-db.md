# 0016. State & audit in Cosmos DB, traces in Application Insights

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0004](0004-documentation-agent-story.md), [0008](0008-human-in-the-loop-approval.md), [0012](0012-agent-identity-and-rbac.md), [architecture §7](../architecture.md#7-audit-record), risk [R1](../risks.md#r1)

## Context

Every run must be reconstructable afterwards: what was asked, what the agent concluded, on which evidence, with which versions, who approved it and what was written. Approval-gated tool calls must survive the gap between proposal and decision, which can be minutes or days ([R1](../risks.md#r1)). Traces alone are sampled, retention-bound and not designed as a system of record.

## Decision

- **Cosmos DB** is the **state & audit store**:
  - **Runs**: status and all versions (agent, model, prompt, policy, contract).
  - **AgentResults**: full payloads.
  - **Review decisions**: decision, approver, timestamp and feedback. Together these form the **full audit table**.
  - **Pending approval-gated tool calls**: tool name, argument hash and status. The runtime resumes or rejects these.
- **Application Insights** (OpenTelemetry) holds traces, metrics and token usage. The `trace_id` is stored on the run for correlation.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Application Insights only | Sampling and retention limits; not a system of record and cannot drive resume |
| Azure SQL | Viable, but the document-shaped payloads fit Cosmos better |
| Foundry thread/conversation storage only | Doesn't cover review decisions or a custom audit schema |

## Consequences

- **Positive:** a complete, queryable audit trail and durable approval state.
- **Negative:** another data store to secure and manage retention for.
- **Follow-ups:** a run row in M1, and the full audit schema plus pending approvals in M2.
