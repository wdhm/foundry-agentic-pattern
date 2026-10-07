# 0011. Knowledge: Foundry IQ for stable knowledge, Toolbox live calls for versioned/volatile data

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0006](0006-sources-and-trigger.md), [0008](0008-human-in-the-loop-approval.md), [0012](0012-agent-identity-and-rbac.md), [architecture §5](../architecture.md#5-knowledge-strategy)

## Context

The agent needs two kinds of information:
- **Stable knowledge** (documentation standard, ADRs, related wiki content), which benefits from semantic search.
- **Versioned or volatile data** (code/IaC/config at a specific commit, the *current* wiki page, work item revisions). This data must be exact, because findings must cite evidence at an exact version.

An index is always somewhat stale, so it cannot reliably provide an exact version.

## Decision

- **Foundry IQ (Azure AI Search)** for stable knowledge: the documentation standard, ADRs, and the wiki for semantic discovery.
- **Foundry Toolbox live calls** for versioned and volatile data:
  - **GitHub MCP**: code/IaC/config at the **exact commit SHA**, and the PR diff.
  - **Azure DevOps MCP/REST**: **work items** (with revision) and the **current wiki page** (with version/ETag), plus the approval-gated **wiki write**.
- **Evidence always points to an exact version.** Index hits are used for discovery. When a hit is cited, the agent re-reads the source live to pin its version.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Index everything (incl. code) in AI Search | Stale and loses exact versions, so evidence cannot be pinned |
| Live calls only | No semantic retrieval over the standard and ADRs; more tokens and latency |
| Custom tool APIs instead of Toolbox/MCP | More code to maintain, and loses platform-managed connections and approvals |

## Consequences

- **Positive:** verifiable evidence, fresh data where it matters, and semantic search where it helps.
- **Negative:** two access paths to maintain, and the index needs a refresh pipeline.
- **Follow-ups:** index and Toolbox connections in M2 (P2).
