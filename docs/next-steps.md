# Next steps (beyond v1)

These topics are **intentionally out of scope** for the v1 repo. They are covered in the workshop and in the slides as the natural evolution of the pattern.

In the workshop, each topic is presented **on slides only**, at the end of its owner's lane (see the [feature map](workshop/feature-map.md)):

| Topic | Lane | Section | Issue |
|---|---|---|---|
| A2A hand-over (Publisher agent) | P1 | [1](#1-agent-to-agent-a2a-separate-publisher-agent) | [#43](https://github.com/wdhm/foundry-agentic-pattern/issues/43) |
| Agent 365 | P2 | [3](#3-agent-365) | [#46](https://github.com/wdhm/foundry-agentic-pattern/issues/46) |
| Work IQ | P2 | [4](#4-work-iq) | [#47](https://github.com/wdhm/foundry-agentic-pattern/issues/47) |
| PDF / SharePoint document sources | P2 | [8](#8-pdf--sharepoint-document-sources) | [#48](https://github.com/wdhm/foundry-agentic-pattern/issues/48) |
| Landing zones & subscription vending | P3 | [2](#2-landing-zone--subscription-vending) | [#50](https://github.com/wdhm/foundry-agentic-pattern/issues/50) |
| Deploy strategy (PTU · spillover · regions) | P3 | [5](#5-model-deployment-strategy) | [#51](https://github.com/wdhm/foundry-agentic-pattern/issues/51) |
| On-behalf-of identity, more agents | – | [6](#6-on-behalf-of-obo-identity), [7](#7-more-agents-on-the-same-pattern) | – |
| Production hardening (out of MVP scope) | All | [9](#9-production-hardening-out-of-mvp-scope) | [ADR 0022](adr/0022-mvp-scope-platform-first.md) |

## 1. Agent-to-Agent (A2A): separate Publisher agent

**Today (v1):** one agent analyses the change and, after approval, writes to the wiki through an approval-gated tool ([ADR 0007](adr/0007-single-agent-in-v1.md)).

**Next:** split the work into
- an **Analyst agent** (read-only identity) that produces the `AgentResult`, and
- a **Publisher agent** with its **own write identity** that only accepts approved proposals and applies them.

**Benefits:** stronger separation of duties, a smaller blast radius, and a reusable publisher across many analyst agents.
**Cost:** more moving parts and more identities to manage. A2A contracts and tracing must also span both agents.

## 2. Landing zone & subscription vending

- Run agents in an **application landing zone**, with the platform team owning networking, policy and identity guardrails.
- Use **subscription vending** to give each agent product team a pre-governed subscription or resource group with Foundry, AI Search, Cosmos DB and Monitor already wired.
- Make **private networking** (private endpoints, VNet-injected agents) and **Azure Policy** (allowed regions/models, diagnostic settings) the default.

## 3. Agent 365

Bring the agent fleet under **Agent 365** for enterprise-wide agent inventory, governance, lifecycle and access control across Microsoft 365. This complements Foundry fleet management, which covers build and runtime.

## 4. Work IQ

Use **Work IQ** to let agents ground on organisational work context (people, meetings, documents, conversations) where appropriate. For the Documentation Agent, this could mean finding the right reviewer or related discussions. It needs careful scoping of data access and consent.

## 5. Model deployment strategy

The v1 repo deploys one chat model and one eval model in a single region. At production scale, consider:
- **Provisioned throughput (PTU)** for predictable latency and cost on baseline load.
- **Spillover** from PTU to standard/global deployments for peaks.
- **Multi-region** deployments behind the AI Gateway for resilience and data-residency constraints.
- **Model version pinning and upgrades** gated by the same eval gate.

## 6. On-behalf-of (OBO) identity

Instead of the agent's own identity, act **on behalf of the requesting user** so that source permissions are enforced per user. This fits interactive scenarios. It is less suitable for CI-triggered runs ([ADR 0012](adr/0012-agent-identity-and-rbac.md)).

## 7. More agents on the same pattern

Candidates that reuse the contract, identity, approval, audit, eval and CI/CD building blocks:
- Architecture review agent (ADR compliance)
- Runbook / operations documentation agent
- Release notes agent

## 8. PDF & SharePoint document sources

v1 reads code, configuration and IaC from Git, and reads wiki pages and work items from Azure DevOps. Many organisations also keep design documents, specifications and vendor documentation as **PDFs** or in **SharePoint**. Next steps:
- Index PDFs and SharePoint libraries into **Foundry IQ** with a SharePoint or Blob knowledge source, so the agent can ground on them alongside the documentation standard and ADRs.
- Keep **evidence exact**. Cite the document URL plus a version (SharePoint version / ETag, or blob hash) and the page or section, so the "evidence at an exact version" rule still holds.
- Respect **document permissions**. Either index only libraries that the agent identity may read, or use OBO / permission-trimmed retrieval ([section 6](#6-on-behalf-of-obo-identity)).
- Optionally make SharePoint a **write target** as well as a source, behind the same approval-gated tool pattern as the wiki.

## 9. Production hardening (out of MVP scope)

The workshop builds an MVP that shows the platform ([ADR 0022](adr/0022-mvp-scope-platform-first.md)). These items make it production-grade. They are explained on slides, not built. Items marked *proposal* are pending P1/P3 confirmation.

| Item | Why it matters | Lane |
|---|---|---|
| Least-privilege Azure DevOps access: a custom group with only work item read and wiki contribute, plus a role-based access matrix per source | Smaller blast radius than Basic + Contributors | P2 ([#22](https://github.com/wdhm/foundry-agentic-pattern/issues/22)) |
| Run id + approver in the wiki commit message, and ETag optimistic concurrency on wiki writes | Stronger audit trail, no lost updates | P2 ([#21](https://github.com/wdhm/foundry-agentic-pattern/issues/21)) |
| Azure Repos as an additional code source | Same pattern as GitHub, via the Azure DevOps MCP server | P2 ([#44](https://github.com/wdhm/foundry-agentic-pattern/issues/44)) |
| Multi-agent identity gateway (agent identity → agent user map), private ingress, logs in Log Analytics | Serve many agents from one gateway; no public endpoint | P2 ([ADR 0021](adr/0021-agent-user-and-ado-mcp-gateway.md)) |
| Mock data generator with seed/reset scripts | Repeatable demo state at scale | P2 ([#17](https://github.com/wdhm/foundry-agentic-pattern/issues/17)) |
| Dedicated audit store in Cosmos DB (runs, decisions, pending approvals) *(proposal)* | Long-term, queryable audit beyond trace retention | P1 ([ADR 0016](adr/0016-state-and-audit-cosmos-db.md)) |
| Hosted agent with custom code *(proposal: one demo or slide)* | Full control of orchestration | P1 ([ADR 0009](adr/0009-hosted-agent-runtime.md)) |
| Onboarding new agents from CI *(proposal)* | No manual step per new agent | P3 ([#28](https://github.com/wdhm/foundry-agentic-pattern/issues/28)) |
| Custom eval metrics, ground-truth gate and a custom monitoring workbook *(proposal)* | Quality bar tailored to the organisation | P3 ([ADR 0013](adr/0013-evaluation-gate-in-ci.md)) |
| APIM AI Gateway with FinOps cost attribution per agent/version *(proposal)* | Cost control and chargeback | P3 ([R4](risks.md#r4)) |
