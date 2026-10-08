# infra/

Infrastructure as code for the pattern, deployed with the **Azure Developer CLI** (`azd up`) and **Bicep**.

> Placeholder. Per [ADR 0020](../docs/adr/0020-manual-setup-first.md), the environment is set up **manually** during M0–M3 following [docs/setup.md](../docs/setup.md). That runbook gets codified here as `azd` + Bicep in **M4** ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).

## Planned scope ([ADR 0014](../docs/adr/0014-infrastructure-scope.md))

| Resource | Purpose |
|---|---|
| Microsoft Foundry resource + project | Hosts the agent, Toolbox, Foundry IQ connection and evaluations |
| Model deployments | One **chat** model for the agent and one **eval** model for evaluators |
| Azure AI Search | Backs Foundry IQ knowledge (documentation standard, ADRs, wiki) |
| Application Insights + Log Analytics | Traces, logs and cost-attribution queries |
| AI Gateway (API Management) | Token limits per project/deployment and FinOps tagging ([R4](../docs/risks.md#r4)) |
| Cosmos DB | Runs, `AgentResult`s, review decisions and pending approvals ([ADR 0016](../docs/adr/0016-state-and-audit-cosmos-db.md)) |
| RBAC | Role assignments for the project managed identity. Agent identity role assignments run as a **post-deploy step** ([R3](../docs/risks.md#r3)). |

Default region: **Sweden Central** ([ADR 0018](../docs/adr/0018-region-sweden-central.md)).

## Out of scope (documented only)

Landing zone and subscription vending, Agent 365, Work IQ, and advanced model deployment strategy (PTU/spillover/multi-region) are covered in [docs/next-steps.md](../docs/next-steps.md).

**Owner:** P3 (AgentOps & platform): Louise ([@llandinl](https://github.com/llandinl))
