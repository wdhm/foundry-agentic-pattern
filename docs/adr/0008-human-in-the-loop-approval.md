# 0008. Human-in-the-loop: approval-gated wiki-write tool; agent published to Teams (Approve / Modify / Reject)

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0004](0004-documentation-agent-story.md), [0009](0009-hosted-agent-runtime.md), [0012](0012-agent-identity-and-rbac.md), [0016](0016-state-and-audit-cosmos-db.md), risks [R1](../risks.md#r1), [R2](../risks.md#r2)

## Context

The agent proposes changes to a system of record (the wiki). Writes must only happen after an accountable human has approved them, and the approver must be traceable. Reviewers already work in Microsoft Teams.

## Decision

- The wiki-write tool is configured in the Toolbox with **`require_approval: always`**.
- The **hosted agent runtime enforces the approval**. The Toolbox MCP endpoint does not block `tools/call` on its own ([R1](../risks.md#r1)). The runtime pauses, **persists the pending tool call** (Cosmos DB), collects the decision, and then **resumes or rejects that exact call**.
- The agent is **published to Microsoft Teams**. Reviewers choose:
  - **Approve**: execute the pending wiki write.
  - **Modify**: send feedback to the agent, which produces a new proposal and a new pending call.
  - **Reject**: no change, and the run is closed.
- Because published agents in Teams **do not support streaming or citations**, **evidence is rendered inline in the message body** ([R1](../risks.md#r1)).
- Publishing uses the **"Just you"** scope for the demo, which needs no admin approval ([R2](../risks.md#r2)).
- The approver is recorded in the **audit record** and in the **wiki commit message**.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Approval via GitHub PR review | Reviewers of documentation are not necessarily GitHub users, and it couples HITL to the trigger |
| Custom approval web app | More to build and host; Teams is where reviewers already are |
| Rely on Toolbox `require_approval` alone | Not enforced at the MCP endpoint ([R1](../risks.md#r1)) |

## Consequences

- **Positive:** a clear accountability point and an auditable approver, in a familiar UX.
- **Negative:** the approval interrupt and resume logic is custom runtime code that must be tested. Teams rendering is limited (no streaming or citations).
- **Follow-ups:** an M0 spike on the Teams approval UX, and an M2 implementation.
