# src/agents/documentation-agent/

The **Documentation Agent**: a Microsoft Foundry **hosted agent** (container) built with the **Microsoft Agent Framework** ([ADR 0009](../../../docs/adr/0009-hosted-agent-runtime.md)).

> Placeholder. A stub agent arrives in **M1** and the real logic in **M2**.

## Responsibilities
1. Accept an `AgentRequest` and nothing else. The agent is trigger-agnostic ([ADR 0006](../../../docs/adr/0006-sources-and-trigger.md)).
2. Retrieve stable knowledge from Foundry IQ, and versioned or volatile data through Toolbox live calls ([ADR 0011](../../../docs/adr/0011-knowledge-foundry-iq-and-toolbox.md)).
3. Perform a gap analysis against the documentation standard.
4. Return a schema-valid `AgentResult` in which every finding is backed by evidence at an exact version, and anything unknown is reported as **"Information missing"**.
5. Persist the run, the result and the review decision to Cosmos DB, and emit traces to Application Insights.
6. For an approved result, call the **approval-gated** wiki-write tool. The runtime pauses, collects the Teams decision, and resumes or rejects that exact tool call ([ADR 0008](../../../docs/adr/0008-human-in-the-loop-approval.md), [R1](../../../docs/risks.md#r1)).

## Planned layout
```text
documentation-agent/
├── Dockerfile
├── agent.yaml            # Hosted agent definition
├── app/                  # Agent Framework app (entry point, workflow, prompts)
├── prompts/              # Versioned system prompts
└── policies/             # Versioned policies (e.g. "never fabricate")
```

**Owner:** P1 (Agent architecture)
