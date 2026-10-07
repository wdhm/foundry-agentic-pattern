# 0017. Ownership: three tracks (P1 / P2 / P3)

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** John ([@johnsward](https://github.com/johnsward)), Rickard ([@wdhm](https://github.com/wdhm)), Louise ([@llandinl](https://github.com/llandinl))
- **Related:** [CODEOWNERS](../../.github/CODEOWNERS), [workshop agenda](../workshop/agenda.md)

## Context

Three people build and deliver the pattern. Clear ownership avoids gaps and duplicated work, and makes it obvious who presents what in the workshop.

## Decision

| Track | Lane | Owner | Scope |
|---|---|---|---|
| **Agent architecture** | **P1** | John ([@johnsward](https://github.com/johnsward)) | Hosted agent, contract, state/Cosmos DB, Teams HITL |
| **Knowledge & identity** | **P2** | Rickard ([@wdhm](https://github.com/wdhm)) | Foundry IQ, Toolbox/MCP, Agent ID, RBAC, mock data |
| **AgentOps & platform** | **P3** | Louise ([@llandinl](https://github.com/llandinl)) | Infra/azd, AI Gateway/FinOps, evals, CI/CD, rollback, tracing |

- Ownership is mirrored in `CODEOWNERS`, in the issue assignees, and in the GitHub labels `area:architecture`, `area:knowledge-identity` and `area:agentops-platform`.
- Each owner presents their track in the workshop.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Shared ownership of everything | Unclear accountability |
| Split by milestone instead of by area | Context-switching; weaker expertise per area |

## Consequences

- **Positive:** clear accountability and parallel work in M2.
- **Negative:** cross-track interfaces (contract ↔ tools ↔ evals) need explicit coordination through PRs and ADRs.
