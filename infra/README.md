# infra/

Manual setup and inventory scripts for the pattern. Full **Azure Developer CLI**
(`azd up`) + **Bicep** provisioning remains future work, not a runnable path here.

> Per [ADR 0020](../docs/adr/0020-manual-setup-first.md) and accepted
> [ADR 0022](../docs/adr/0022-mvp-scope-platform-first.md), the environment is set
> up **manually** following [docs/setup.md](../docs/setup.md). Codifying it as
> full `azd` + Bicep is deferred/optional
> ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).

Existing scripts cover read-only platform inventory, approved native monitoring
setup, Foundry IQ/GitHub connections, manual agent onboarding and the read-only
hosted toolbox. Follow each script's approval and identity boundaries; rerunning
onboarding can repoint the shared single-agent ADO gateway. No full clean-
subscription provisioning/teardown or automated RBAC workflow is implemented.

An optional [AI gateway module](ai-gateway/main.bicep) now prepares model and
read-Toolbox routes on an **existing** APIM instance. It is not deployed, wired
into CI, or a replacement for the ADO identity gateway. See the
[integration/review guide](../docs/ai-gateway.md) for independent opt-ins,
coverage gaps, identity/cost prerequisites and direct-mode rollback.
The independent [assessment ingress module](ai-gateway/agent-ingress.bicep)
adds only a fixed named-agent Responses operation for the opt-in hosted CLI,
with a separate client identity allowlist. It does not proxy session control,
Teams Activity or approved writes.

## Future IaC scope ([ADR 0014](../docs/adr/0014-infrastructure-scope.md))

This is the original target backlog, not deployed-resource evidence or a
restoration of deferred Cosmos DB, custom workbooks or APIM to MVP scope.

| Resource | Purpose |
|---|---|
| Microsoft Foundry resource + project | Hosts the agent, Toolbox, Foundry IQ connection and evaluations |
| Model deployments | One **chat** model for the agent and one **eval** model for evaluators |
| Azure AI Search | Backs Foundry IQ knowledge (documentation standard in the MVP). Set up by [`scripts/setup-foundry-iq.ps1`](scripts/setup-foundry-iq.ps1) |
| Application Insights + Log Analytics | Traces, logs and cost-attribution queries |
| AI Gateway (API Management) | Token limits per project/deployment and FinOps tagging ([R4](../docs/risks.md#r4)) |
| Cosmos DB | Runs, `AgentResult`s, review decisions and pending approvals ([ADR 0016](../docs/adr/0016-state-and-audit-cosmos-db.md)) |
| RBAC | Role assignments for the project managed identity. Agent identity role assignments run as a **post-deploy step**: [`scripts/onboard-agent.ps1`](scripts/onboard-agent.ps1) ([R3](../docs/risks.md#r3)). |

Default region: **Sweden Central** ([ADR 0018](../docs/adr/0018-region-sweden-central.md)).

## Out of scope (documented only)

Landing zone and subscription vending, Agent 365, Work IQ, and advanced model deployment strategy (PTU/spillover/multi-region) are covered in [docs/next-steps.md](../docs/next-steps.md).

**Owner:** P3 (AgentOps & platform): Louise ([@llandinl](https://github.com/llandinl))
