# Manual setup runbook

> **Why manual?** [ADR 0020](adr/0020-manual-setup-first.md): during M0–M3 we set up Azure by hand. This runbook is the **single source of truth** for the environment, and it gets codified as `azd` + Bicep in M4 ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).
>
> **Owner:** P3: Louise ([@llandinl](https://github.com/llandinl)), [#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5). **Rule:** if you change anything in Azure, update this file in the same PR.

## Conventions

| Item | Value |
|---|---|
| Region | **Sweden Central** ([ADR 0018](adr/0018-region-sweden-central.md)) |
| Resource group | `rg-fap-dev` |
| Naming | `<type>-fap-dev` (e.g. `aif-fap-dev`, `proj-fap-dev`, `cosmos-fap-dev`); lowercase, no secrets in names |
| Tags | `project=foundry-agentic-pattern`, `env=dev`, `owner=<alias>` |
| Access | All three owners get **Contributor** on `rg-fap-dev` + **Azure AI User** on the Foundry project |

## Phase 1: Base (needed by all tracks, M0/M1)

- [ ] Resource group `rg-fap-dev` in Sweden Central
- [ ] **Foundry resource** + **Foundry project**
- [ ] **Model deployments**: one **chat** model (agent) and one **eval** model (evaluators). Record the model and version below.
- [ ] **Log Analytics** + **Application Insights**, connected to the Foundry project (tracing)
- [ ] **Cosmos DB** (NoSQL, serverless) with database `fap` and containers `runs`, `results`, `approvals` ([ADR 0016](adr/0016-state-and-audit-cosmos-db.md))
- [ ] RBAC: team members as above. Project managed identity → Cosmos DB data contributor.
- [ ] **Test Azure DevOps** org/project with a wiki and a few work items (fictional data, [ADR 0005](adr/0005-generic-repo-with-fictional-data.md)). Needed by the P2 spike [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2).

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
| `AZURE_SUBSCRIPTION_ID` | |
| `AZURE_RESOURCE_GROUP` | `rg-fap-dev` |
| `AZURE_LOCATION` | `swedencentral` |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project → Overview |
| `CHAT_MODEL_DEPLOYMENT` | |
| `EVAL_MODEL_DEPLOYMENT` | |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights → Overview |
| `COSMOS_ENDPOINT` | Cosmos DB → Overview |
| `AZURE_DEVOPS_ORG_URL` | |
| `AZURE_DEVOPS_PROJECT` | |

## Change log

| Date | Who | Change |
|---|---|---|
| | | |
