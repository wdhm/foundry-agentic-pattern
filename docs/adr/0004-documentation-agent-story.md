# 0004. Documentation Agent story: implementation → gap analysis → proposal + evidence → human review → wiki

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0006](0006-sources-and-trigger.md), [0008](0008-human-in-the-loop-approval.md), [0010](0010-python-and-pydantic-contracts.md), [0013](0013-evaluation-gate-in-ci.md)

## Context

The reference agent has to be small enough to build and explain in a half day. It also has to exercise every part of the pattern: contract, knowledge, tools, identity, approval, audit, evals and release. Documentation drift after implementation changes is a common, relatable problem with a clear "right answer" that can be evaluated.

## Decision

The Documentation Agent v1 follows this story:

1. An **implementation change** (a PR touching `samples/**`) triggers the agent through an `AgentRequest`.
2. The agent reads **controlled sources**: code/IaC/config at the exact commit, the existing wiki, work items/requirements, ADRs and the documentation standard.
3. It performs a **gap analysis** against the documentation standard.
4. It returns an **`AgentResult`** containing:
   - documentation status,
   - findings (category, severity, description),
   - proposed changes,
   - missing information,
   - source references / evidence,
   - confidence,
   - `requires_human_review`.
5. **Human review in Teams**:
   - **Approve**: the wiki is updated.
   - **Modify**: the feedback is sent back to the agent.
   - **Reject**: nothing changes.
6. **Hard rule:** unknown facts are reported as **"Information missing"** and are never fabricated.
7. Every output is logged with the **agent, model, prompt, policy and contract version**.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Fully autonomous wiki updates | Unacceptable risk for a system of record, and it does not demonstrate governance |
| Q&A / chat-over-docs agent | Common and hard to evaluate objectively; it does not exercise write approval |
| Code review agent | Crowded space with overlapping GitHub-native features |

## Consequences

- **Positive:** an objectively evaluable task (planted gaps), a natural human-approval point, and a clear audit narrative.
- **Negative:** quality depends on the documentation standard and the source coverage, both of which are swappable.
- **Follow-ups:** contract definition (M1), planted gaps and ground truth (M2).
