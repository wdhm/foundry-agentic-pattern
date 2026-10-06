# Workshop agenda: Agentic Pattern on Microsoft Foundry

**Format:** half day (09:00–12:00), **demo-driven**, run against a **pre-deployed environment in a shared tenant** ([ADR 0002](../adr/0002-workshop-format.md)).
**Audience:** customer architects and technical decision makers ([ADR 0001](../adr/0001-audience-and-delivery.md)).
**Take-away:** this repository. Fork it privately, plug in your own sources and documentation standard, and run `azd up`.

The agenda follows the three **swimlanes** in the [feature map](feature-map.md) and the [feature swimlanes diagram](../diagrams/feature-swimlanes.html) ([PNG](../diagrams/feature-swimlanes.png)). Each presenter owns one block. **Built** features are demoed live, and **slides-only** topics close each block as next steps ([next-steps.md](../next-steps.md)). F-tags (F1–F8) match the diagrams.

**Presenters**
- **P1**: Agent architecture (area 01)
- **P2**: Knowledge & identity (areas 02 + 03)
- **P3**: AgentOps & platform (area 04)

## Overview

| Time | Block | Lead |
|---|---|---|
| 09:00–09:15 | Welcome & framing | P1 |
| 09:15–09:35 | Live end-to-end demo | P1 |
| 09:35–10:15 | **P1 · Agent architecture** | P1 |
| 10:15–10:30 | ☕ Break | |
| 10:30–11:10 | **P2 · Knowledge & identity** | P2 |
| 11:10–11:50 | **P3 · AgentOps & platform** | P3 |
| 11:50–12:00 | Fork & adapt + Q&A | All |

## 09:00–09:35 · Opening (P1)

| Time | Item | Type | Content |
|---|---|---|---|
| 09:00–09:15 | Welcome & framing | Slides | Why a *pattern*, not just an agent. The Documentation Agent story, the [reference architecture](../diagrams/reference-architecture.html), and what you take home. |
| 09:15–09:35 | Live end-to-end demo | Demo | PR on the sample integration → `AgentResult` → Teams approval → wiki updated |

## 09:35–10:15 · P1 · Agent architecture

| Time | Feature | F | Type | Content |
|---|---|---|---|---|
| 09:35–09:40 | App / Foundry architecture + fleet registry | – | Demo | Components and owners; the agent in Foundry fleet management ([#42](https://github.com/wdhm/foundry-agentic-pattern/issues/42)) |
| 09:40–09:50 | Hosted agent | F2 | Demo | Hosted agent on Agent Framework (Python), the core product that everything plugs into |
| 09:50–09:58 | Output contract | F4 | Demo | `AgentRequest` → JSON `AgentResult`, evidence at exact versions, "Information missing" |
| 09:58–10:05 | Human-in-the-loop | F5 | Demo | Publish to Teams, Approve / Modify / Reject, approval-gated wiki write |
| 10:05–10:10 | State & audit | – | Demo | Cosmos DB run record: versions, decision, approver |
| 10:10–10:15 | *A2A hand-over* | – | Slides | Analyst + Publisher agent with separate identities ([#43](https://github.com/wdhm/foundry-agentic-pattern/issues/43)) |

## 10:30–11:10 · P2 · Knowledge & identity

| Time | Feature | F | Type | Content |
|---|---|---|---|---|
| 10:30–10:35 | Mock data | F8 | Demo | Fictional sample integration, wiki, work items, planted gaps + ground truth |
| 10:35–10:45 | Foundry IQ | F3 | Demo | Stable knowledge: documentation standard, ADRs, wiki |
| 10:45–10:53 | Toolbox (MCP · REST · DevOps) | F1 | Demo | Live calls for code/IaC/config at commit, work items, current wiki page |
| 10:53–10:57 | Integration patterns | – | Demo | Azure DevOps wiki + Azure Repos as source and target ([#44](https://github.com/wdhm/foundry-agentic-pattern/issues/44)) |
| 10:57–11:03 | Identities & resource org | – | Demo | Agent ID, least privilege per source, project vs agent scope ([#22](https://github.com/wdhm/foundry-agentic-pattern/issues/22), [#45](https://github.com/wdhm/foundry-agentic-pattern/issues/45)) |
| 11:03–11:10 | *Agent 365 · Work IQ · PDF/SharePoint* | – | Slides | Fleet governance across M365 ([#46](https://github.com/wdhm/foundry-agentic-pattern/issues/46)), work context ([#47](https://github.com/wdhm/foundry-agentic-pattern/issues/47)), document sources ([#48](https://github.com/wdhm/foundry-agentic-pattern/issues/48)) |

## 11:10–11:50 · P3 · AgentOps & platform

| Time | Feature | F | Type | Content |
|---|---|---|---|---|
| 11:10–11:18 | AI Gateway (FinOps · tokenomics · limits) | – | Demo | APIM token limits per project + deployment, cost per agent/version |
| 11:18–11:23 | Model deployments | – | Demo | Chat + eval model, version pinning ([#49](https://github.com/wdhm/foundry-agentic-pattern/issues/49)) |
| 11:23–11:33 | Evals & observability | F6 | Demo | Traces in App Insights; the eval gate blocks a bad version |
| 11:33–11:43 | Versioning & CI/CD | F7 | Demo | `azd up`, GitHub Actions, agent versions, rollback via `version_selector` |
| 11:43–11:50 | *Landing zones · Deploy strategy* | – | Slides | Subscription vending ([#50](https://github.com/wdhm/foundry-agentic-pattern/issues/50)); PTU, spillover, regions ([#51](https://github.com/wdhm/foundry-agentic-pattern/issues/51)) |

## 11:50–12:00 · Fork & adapt + Q&A (All)

How to fork the repo, swap in your own sources and documentation standard, and plan next steps with your team.

## Demo checklist (pre-workshop)
- [ ] Environment deployed with `azd up` in the shared tenant (Sweden Central)
- [ ] Mock data seeded (wiki, work items, ADRs, documentation standard)
- [ ] Agent published to Teams; presenters have access
- [ ] A prepared PR with planted gaps ready to open live
- [ ] A prepared "bad" agent version that fails the eval gate
- [ ] Two agent versions deployed for the rollback demo
- [ ] Backup recording of the end-to-end demo
