# 0024. Hosted Agent Framework app as the main documentation runtime

- **Status:** Proposed for review; P1 direction confirmed by John on 2026-10-16
- **Date:** 2026-10-16
- **Deciders:** P1 (John)
- **Related:** [0009](0009-hosted-agent-runtime.md), [0022](0022-mvp-scope-platform-first.md), [0023](0023-versioned-structured-output-contract.md), #13

## Context

ADR 0022 selected the existing prompt agent for the MVP. The hosted
`documentation-agent` remained a v0 contract stub. The prompt-agent version of
the assessment now demonstrates the v1 schema, source retrieval and gap
analysis, but does not implement P1's reusable Python runtime.

John confirmed that the main documentation workflow should use the hosted
Agent Framework application. This revises the runtime choice, not every other
MVP scope decision.

## Decision

- Develop `documentation-agent` into the main hosted documentation runtime.
  The Python app must own request validation, model/tool execution, result
  validation and caller-owned provenance. Merely forwarding requests to
  `doc-agent` is not the intended implementation.
- Reuse the v1 contract, versioned assessment instructions and policies,
  Foundry IQ standard, GitHub source access and Azure DevOps integration.
  Preserve existing prompt-agent work as a reference during migration.
- Keep #13 assessment-only: expose read operations, produce proposals, and
  do not execute wiki writes. Native prompt-agent approval behaviour must not
  be assumed to protect hosted tool calls. Approval enforcement is a separate
  hosted-runtime task before enabling any write tool.
- Do not reintroduce Cosmos DB or a custom audit store merely because the
  runtime is hosted; those remain separate scope decisions.
- Leave the deployed `doc-agent` and its source access unchanged until an
  explicitly coordinated transition. The current ADO gateway serves one agent
  identity; `onboard-agent.ps1` re-points it to the selected agent. Running it
  for the hosted agent is therefore not an isolated permission change.
- Do not count the prompt-agent scenario results as proof that hosted #13 is
  complete. The hosted implementation needs its own source-authentication,
  contract and scenario verification.

## Consequences

The existing assessment rules and tests are reusable, but model/tool wiring and
hosted identity access still need implementation and verification. The
prompt-agent demo remains available while this work is performed.

## Ownership and transition

P1 implements the hosted runtime and read-only guards under #13. P2 supplies
toolbox resources, source connections and coordinated identity/gateway access;
this change does not create them. Once the hosted workflow is verified, the
intended end state is hosted-only agent consumers. Retiring the prompt agent
and its unused permissions happens after that verification, not during local
implementation. The read-only assessment does not complete #15 (human approvals).
