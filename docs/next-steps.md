# Next steps (beyond v1)

These topics are **intentionally out of scope** for the v1 repo. They are covered in the workshop and in the slides as the natural evolution of the pattern.

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
