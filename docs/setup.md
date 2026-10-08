# Manual setup runbook

> **Why manual?** [ADR 0020](adr/0020-manual-setup-first.md): during M0–M3 we set up Azure by hand. This runbook is the **single source of truth** for the environment, and it gets codified as `azd` + Bicep in M4 ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).
>
> **Owner:** P3: Louise ([@llandinl](https://github.com/llandinl)), [#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5). **Rule:** if you change anything in Azure, update this file in the same PR.

## Shared workshop environment

This is **the** environment for development and the workshop. Don't create parallel resource groups or Foundry resources; add to these.

| Item | Value |
|---|---|
| Tenant | `M365CPI54615665.onmicrosoft.com` (has M365/Teams, needed for [#1](https://github.com/wdhm/foundry-agentic-pattern/issues/1) and [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4)) |
| Subscription | `ME-M365CPI54615665-rwidholm-1` |
| Region | **Sweden Central** ([ADR 0018](adr/0018-region-sweden-central.md)) |
| Resource group | `rg-foundry-agentic-pattern` |
| Foundry resource | `foundry-agentic-R8N3LD` (kind `AIServices`, S0) |
| Foundry project | `proj-agentic` |
| Project endpoint | `https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic` |
| Azure DevOps org | [`dev.azure.com/foundry-agentic`](https://dev.azure.com/foundry-agentic), connected to the **same Entra tenant** (required for agent identity, [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2)) |
| Azure DevOps project / wiki | `integration-team` / `integration-team.wiki` (project wiki) |

### Team accounts (sign in to Azure, Foundry and Azure DevOps with these)

| Track | Person | Tenant account | Subscription role |
|---|---|---|---|
| P1 | John | `MarioR@M365CPI54615665.onmicrosoft.com` | Owner |
| P2 | Rickard | `admin@M365CPI54615665.onmicrosoft.com` | Owner |
| P3 | Louise | `SashaO@M365CPI54615665.onmicrosoft.com` | Owner |

Passwords and MFA are never stored in this repo.

Subscription and tenant IDs go in your local `.env`, not in this repo.

**Getting started:**

```powershell
az login --tenant M365CPI54615665.onmicrosoft.com   # sign in with your tenant account
az account set -s ME-M365CPI54615665-rwidholm-1
```

## Conventions

| Item | Value |
|---|---|
| Naming (new resources) | `<type>-foundry-agentic` (e.g. `cosmos-foundry-agentic`, `appi-foundry-agentic`, `srch-foundry-agentic`, `apim-foundry-agentic`); lowercase, no secrets in names |
| Tags | `project=foundry-agentic-pattern`, `owner=<alias>` |
| Access | Each owner signs in with their **tenant account** (below), which is **Owner** on the subscription; add **Azure AI User** on the Foundry project when needed |

## Phase 1: Base (needed by all tracks, M0/M1)

- [x] Resource group `rg-foundry-agentic-pattern` in Sweden Central
- [x] **Foundry resource** `foundry-agentic-R8N3LD` + **Foundry project** `proj-agentic`
- [ ] **Model deployments**: one **chat** model (agent) and one **eval** model (evaluators). Record the model and version below.
- [ ] **Log Analytics** + **Application Insights**, connected to the Foundry project (tracing)
- [ ] **Cosmos DB** (NoSQL, serverless) with database `fap` and containers `runs`, `results`, `approvals` ([ADR 0016](adr/0016-state-and-audit-cosmos-db.md))
- [x] Team access: tenant accounts for John, Rickard and Louise are Owner on the subscription (see the team accounts table)
- [x] All three tenant accounts are users (Basic) in the Azure DevOps org `foundry-agentic`
- [ ] RBAC: project managed identity → Cosmos DB data contributor
- [x] **Azure DevOps** org `foundry-agentic`, project `integration-team`, project wiki (connected to the tenant)
- [ ] A few fictional work items + wiki pages ([ADR 0005](adr/0005-generic-repo-with-fictional-data.md)); replaced by mock data in [#17](https://github.com/wdhm/foundry-agentic-pattern/issues/17). Needed by the P2 spike [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2).

## Phase 2: Added by the tracks (M1–M3)

| Resource | When / issue | Owner |
|---|---|---|
| **Azure AI Search** + Foundry IQ knowledge base | [#19](https://github.com/wdhm/foundry-agentic-pattern/issues/19) | P2 |
| **Agent identity** role assignments (DevOps, GitHub, Search) | [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2), [#28](https://github.com/wdhm/foundry-agentic-pattern/issues/28) | P2 |
| **AI Gateway (APIM)**: token limits + FinOps tagging | [#3](https://github.com/wdhm/foundry-agentic-pattern/issues/3), [#23](https://github.com/wdhm/foundry-agentic-pattern/issues/23) | P3 |
| Hosted agent deployment | [#7](https://github.com/wdhm/foundry-agentic-pattern/issues/7) | P1 |
| Teams / M365 publish | [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4) | P3 |

Document each step here when you do it: portal path or CLI command, settings chosen, and any gotchas.

## Outputs (environment values)

Store these in a local `.env` (git-ignored). Never commit secrets; prefer Entra ID auth over keys.

| Variable | Value / where to find it |
|---|---|
| `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
| `AZURE_TENANT_ID` | `az account show --query tenantId -o tsv` |
| `AZURE_RESOURCE_GROUP` | `rg-foundry-agentic-pattern` |
| `AZURE_LOCATION` | `swedencentral` |
| `FOUNDRY_PROJECT_ENDPOINT` | `https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic` |
| `CHAT_MODEL_DEPLOYMENT` | |
| `EVAL_MODEL_DEPLOYMENT` | |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights → Overview |
| `COSMOS_ENDPOINT` | Cosmos DB → Overview |
| `AZURE_DEVOPS_ORG_URL` | `https://dev.azure.com/foundry-agentic` |
| `AZURE_DEVOPS_PROJECT` | `integration-team` |

## Change log

| Date | Who | Change |
|---|---|---|
| 2026-10-07 | Rickard | Resource group, Foundry resource + project created |
| 2026-10-08 | Rickard | Azure DevOps org/project/wiki created and connected to the tenant; shared environment documented |
