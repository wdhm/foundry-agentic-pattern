# 0006. Sources and trigger: sample integration in GitHub, wiki + work items in Azure DevOps; trigger-agnostic agent

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0003](0003-github-for-code-and-cicd.md), [0010](0010-python-and-pydantic-contracts.md), [0011](0011-knowledge-foundry-iq-and-toolbox.md)

## Context

The agent needs a realistic subject to document and realistic sources to read. Triggers vary between organisations (PR, schedule, chat, ticket), and coupling the agent to one of them would limit reuse.

## Decision

- **Subject:** code, IaC and config of a **fictional sample integration** in `samples/sample-integration/` on GitHub.
- **Other sources:** **wiki** and **work items** in **Azure DevOps**, plus ADRs and the documentation standard (see [0011](0011-knowledge-foundry-iq-and-toolbox.md)).
- **Primary trigger:** a **GitHub Actions** workflow on PRs touching `samples/**` builds an `AgentRequest` and invokes the agent.
- **Fallback trigger:** a **manual CLI** that builds the same `AgentRequest`.
- **The agent is trigger-agnostic.** It only accepts an `AgentRequest`. All trigger-specific logic lives outside the agent.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Agent subscribes to GitHub webhooks directly | Couples the agent to GitHub, so it is not reusable for other triggers |
| Teams/chat as the only trigger | Not tied to implementation changes, which weakens the story |
| Scheduled scans | Useful later, but lacks the PR → review narrative |

## Consequences

- **Positive:** the same agent can be triggered from CI, CLI, chat or a scheduler. Contract tests cover all paths.
- **Negative:** each trigger needs a small adapter that builds the `AgentRequest`.
- **Follow-ups:** CLI in M1, PR workflow in M2.
