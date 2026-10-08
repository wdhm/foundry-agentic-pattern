# 0022. MVP scope: show the platform, keep the flow simple

- **Status:** Accepted for P2; proposed for P1 and P3 (John and Louise confirm their lanes)
- **Date:** 2026-10-08
- **Deciders:** P2 (Rickard); P1 and P3 for their lanes
- **Related:** [0002](0002-workshop-format.md), [0007](0007-single-agent-in-v1.md), [0009](0009-hosted-agent-runtime.md), [0013](0013-evaluation-gate-in-ci.md), [0014](0014-infrastructure-scope.md), [0016](0016-state-and-audit-cosmos-db.md), [0020](0020-manual-setup-first.md), [0021](0021-agent-user-and-ado-mcp-gateway.md); [next steps](../next-steps.md)

## Context

The repo is delivered as a half-day, demo-driven workshop ([ADR 0002](0002-workshop-format.md)). Its job is to **show Microsoft Foundry's tools and platform** on a sound architecture, not to ship a production-hardened agent.

The plan had grown to more than 45 issues, and M1 was still not done. Several items rebuild things the platform already provides: a custom approval store, a Cosmos DB audit schema, a custom monitoring workbook and custom eval metrics. Other items perfect a single flow, such as the least-privilege matrix, ETag concurrency and multi-agent gateway routing. The agent identity → Azure DevOps work ([ADR 0021](0021-agent-user-and-ado-mcp-gateway.md)) showed how fast the details grow.

## Decision

We build an **MVP**: one simple happy path that shows each platform capability once.

**Rules for every feature**
1. **Platform-native first.** Use Foundry's built-in feature (portal, catalog or config) before writing code. We write custom code only when the platform has a real gap, as with the identity gateway in ADR 0021.
2. **One happy path.** We cover only the demo scenario. Edge cases, concurrency, retries and multi-agent support are out of scope.
3. **Done = demoable + documented.** A feature is done when it can be demoed in about 5 minutes and is explained on one page with Microsoft Learn links.
4. **Hardening goes on slides.** Least privilege, private networking, audit stores and FinOps attribution are explained as [next steps](../next-steps.md), not built.

**MVP scope**

| Area | MVP approach | Status |
|---|---|---|
| Agent runtime (P1) | Foundry **prompt agent** (already running). The hosted agent becomes one P1 demo or a slide. | Proposal for P1 |
| Output contract (P1) | Structured JSON output on the agent; the Pydantic models stay the schema source | Proposal for P1 |
| Human-in-the-loop (P1) | **Foundry's native MCP tool approval** (`require_approval`), already proven; Teams as the showcase channel | Proposal for P1 |
| State & audit (P1) | Foundry traces/conversations + the wiki history; no Cosmos DB in the MVP | Proposal for P1 |
| Knowledge (P2) | Foundry IQ knowledge base with the documentation standard and wiki | Decided |
| Tools (P2) | Azure DevOps via the gateway (done, ADR 0021); GitHub source via MCP | Decided |
| Identity (P2) | Agent identity + agent user (done). Least privilege goes on slides. | Decided |
| Mock data (P2) | A small hand-made set with 2–3 planted gaps; no generator | Decided |
| Observability (P3) | Foundry tracing and monitoring views; no custom workbook | Proposal for P3 |
| Evals (P3) | Foundry built-in evaluators on about 5 cases, run from one GitHub Action | Proposal for P3 |
| CI/CD (P3) | One workflow: create the agent version, then run evals. Rollback via `version_selector` is shown manually. | Proposal for P3 |
| AI Gateway (P3) | Foundry's AI gateway option if setup is simple; otherwise slides | Proposal for P3 |
| IaC (P3) | Runbook + scripts are enough for the demo; `azd up` only if time allows | Proposal for P3 |

**Milestones**
- **M1: MVP slice.** Agent + Azure DevOps tools + approval + structured result + Foundry IQ + GitHub source + tracing, triggered from a CLI.
- **M2: Showcase increments.** One feature, one owner, one demo each: Teams publish, evals in CI, versions and rollback, AI gateway, fleet management, hosted agent.
- **M3:** end-to-end demo. **M4:** workshop packaging.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Keep the full v1 plan | Closer to production | Too much custom code; the demo is at risk | The workshop showcases the platform, not hardening |
| Slides only, no build | Fast | No live proof, nothing to fork | Attendees should get a working repo |

## Consequences

- **Positive:** fewer moving parts, faster progress, and more of the demo shows Foundry itself.
- **Negative / trade-offs:**
  - Some earlier ADRs describe the target, not the MVP: [0009](0009-hosted-agent-runtime.md) (hosted agent), [0013](0013-evaluation-gate-in-ci.md) (ground-truth gate), [0016](0016-state-and-audit-cosmos-db.md) (Cosmos DB). They stay valid as the target architecture.
  - The MVP is not production-ready (see the disclaimer in the README).
- **Follow-ups:**
  - P1 and P3 confirm or adjust their proposals (issues labelled `mvp-proposal`).
  - Out-of-scope items are listed in [next-steps.md](../next-steps.md#9-production-hardening-out-of-mvp-scope).
