# Workshop agenda: Agentic Pattern on Microsoft Foundry

**Format:** half day (09:00–12:00), **demo-driven**, run against a **pre-deployed environment in a shared tenant** ([ADR 0002](../adr/0002-workshop-format.md)).
**Audience:** customer architects and technical decision makers ([ADR 0001](../adr/0001-audience-and-delivery.md)).
**Take-away:** this repository. Fork it privately, plug in your own sources and documentation standard, and follow the reviewed manual [setup runbook](../setup.md). Full `azd up` provisioning is deferred/optional, not a verified attendee path.

The agenda follows the three **swimlanes** in the [feature map](feature-map.md) and the [feature swimlanes diagram](../diagrams/feature-swimlanes.html) ([PNG](../diagrams/feature-swimlanes.png)). Each presenter owns one block. **Built** features are demoed live, and **slides-only** topics close each block as next steps ([next-steps.md](../next-steps.md)). F-tags (F1–F8) match the diagrams.

**Readiness update, 2026-10-20:** the times below are the planned workshop, not
evidence of a completed rehearsal. Hosted read-only assessment is demonstrated.
Live approval/wiki writes, Teams, the full hosted eval gate and timed rollback
remain acceptance work. Until those pass, explain them as pending capabilities,
not live demonstrations. Keep the [checklist](#demo-checklist-pre-workshop) and
backup recording aligned with actual results.

**Presenters**
- **P1** John ([@johnsward](https://github.com/johnsward)): Agent architecture (area 01)
- **P2** Rickard ([@wdhm](https://github.com/wdhm)): Knowledge & identity (areas 02 + 03)
- **P3** Louise ([@llandinl](https://github.com/llandinl)): AgentOps & platform (area 04)

## Overview

| Time | Block | Lead |
|---|---|---|
| 09:00–09:15 | Welcome & framing | P1 · John |
| 09:15–09:35 | Live end-to-end demo | P1 · John |
| 09:35–10:15 | **P1 · Agent architecture** | P1 · John |
| 10:15–10:30 | ☕ Break | |
| 10:30–11:10 | **P2 · Knowledge & identity** | P2 · Rickard |
| 11:10–11:50 | **P3 · AgentOps & platform** | P3 · Louise |
| 11:50–12:00 | Fork & adapt + Q&A | All |

## 09:00–09:35 · Opening (P1 · John)

| Time | Item | Type | Content |
|---|---|---|---|
| 09:00–09:15 | Welcome & framing | Slides | Why a *pattern*, not just an agent. The Documentation Agent story, the [reference architecture](../diagrams/reference-architecture.html), and what you take home. |
| 09:15–09:35 | End-to-end story and available assessment | Read-only demo; full path pending | CLI → hosted `AgentResult` with versioned evidence is supported. PR → Teams approval → wiki update remains a planned acceptance path, not a completed demo |

## 09:35–10:15 · P1 · Agent architecture · John

| Time | Feature | F | Type | Content |
|---|---|---|---|---|
| 09:35–09:40 | App / Foundry architecture + fleet registry | – | Demo | Components and owners; the agent in Foundry fleet management ([#42](https://github.com/wdhm/foundry-agentic-pattern/issues/42)) |
| 09:40–09:50 | Hosted agent | F2 | Demo | Hosted agent on Agent Framework (Python), the core product that everything plugs into |
| 09:50–09:58 | Output contract | F4 | Demo | `AgentRequest` → JSON `AgentResult`, evidence at exact versions, "Information missing" ([guide](information-missing-guide.md)) |
| 09:58–10:05 | Human-in-the-loop | F5 | Local integration / planned live demo | Show selected-proposal approval and its safety contract; label real Teams/wiki acceptance pending until verified |
| 10:05–10:10 | State & audit | – | Walkthrough | Native conversations/traces and wiki-history design; Cosmos DB is deferred, not a live MVP run store |
| 10:10–10:15 | *A2A hand-over* | – | Slides | Analyst + Publisher agent with separate identities ([#43](https://github.com/wdhm/foundry-agentic-pattern/issues/43)) |

## 10:30–11:10 · P2 · Knowledge & identity · Rickard

Use the [40-minute P2 presenter guide](p2-presenter-guide.md) for the run order,
fallbacks and hard stops. Demos target hosted **`documentation-agent`** (v13
serving at 100%, recorded 2026-10-21) with its **own** identity and agent user. The
assessment uses only the read-only toolbox. The live PR #62 assessment runs only
if the same request passed at rehearsal on the same serving version; otherwise
show the recorded result.

| Time | Feature | F | Type | Content |
|---|---|---|---|---|
| 10:30–10:35 | Mock data | F8 | Demo | Fictional Order Sync integration, wiki page, work item and the three planted drifts in PR #62 ([data](../../data/README.md)) |
| 10:35–10:43 | Foundry IQ | F3 | Demo | Stable knowledge: the documentation standard as a knowledge base, called as an MCP tool; findings cite rule IDs ([guide](foundry-iq-guide.md)) |
| 10:43–10:55 | Toolbox (MCP · DevOps · GitHub) | F1 | Read-only demo (recorded fallback) | `documentation-agent-readonly` vs `documentation-agent-write`; one assessment of PR #62 → `gaps_found` with pinned evidence ([GitHub guide](github-mcp-guide.md)); same reads from Azure Repos ([guide](azure-devops-workflow-guide.md)). No write tools in an assessment |
| 10:55–11:03 | Identities & resource org | – | Demo | Agent identity and agent user ([guide](agent-identity-guide.md)); which identity each connection presents ([guide](resource-organization-guide.md)); the wiki commit from John's Teams Approve is authored by the agent user. Name the security debt: the agent user is Basic + Contributors for the write path ([#22](https://github.com/wdhm/foundry-agentic-pattern/issues/22)) |
| 11:03–11:10 | *Agent 365 · Work IQ · PDF/SharePoint* | – | [Slides](slides/README.md) | Fleet governance across M365 ([#46](https://github.com/wdhm/foundry-agentic-pattern/issues/46)), work context ([#47](https://github.com/wdhm/foundry-agentic-pattern/issues/47)), document sources ([#48](https://github.com/wdhm/foundry-agentic-pattern/issues/48)) |

## 11:10–11:50 · P3 · AgentOps & platform · Louise

Use the [40-minute P3 presenter guide](p3-presenter-guide.md) for slide order,
recorded evidence, timing and hard stops. The chosen gateway delivery is the
prepared explanatory fallback, not an unapproved live configuration/demo.

| Time | Feature | F | Type | Content |
|---|---|---|---|---|
| 11:10–11:18 | AI Gateway (FinOps · tokenomics · limits) | – | [Prepared explanatory slides](slides/ai-gateway.md) | Distinguish service quota, project/deployment limits and per-agent cost attribution. No live cost/429 proof or configuration change |
| 11:18–11:23 | Model deployments | – | Inventory walkthrough | Existing chat and IQ embeddings, configured version versus upgrade-policy pinning; evaluator/quota/cost decision remains open ([#49](https://github.com/wdhm/foundry-agentic-pattern/issues/49)) |
| 11:23–11:33 | Evals & observability | F6 | Available evidence + pending showcase | Five pinned cases, verified hosted result and native prompt/hosted model/tool spans. Show the recorded native correlation; label the full hosted good/bad gate pending |
| 11:33–11:43 | Versioning & CI/CD | F7 | CLI/workflow walkthrough; rollback pending | Manual setup, hosted CLI, offline/manual GitHub Action and serving-pin safeguards. Do not present `azd up`, promotion or timed rollback as completed |
| 11:43–11:50 | *Landing zones · Deploy strategy* | – | Slides | Subscription vending ([#50](https://github.com/wdhm/foundry-agentic-pattern/issues/50)); PTU, spillover, regions ([#51](https://github.com/wdhm/foundry-agentic-pattern/issues/51)) |

## 11:50–12:00 · Fork & adapt + Q&A (All)

How to fork the repo, swap in your own sources and documentation standard, and plan next steps with your team.

## Demo checklist (pre-workshop)
- [x] Shared environment and source fixtures documented in the manual runbook; full `azd up` is deferred/optional with [#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)
- [x] One read-only hosted version-6 assessment completed with verified contract/source versions/reviewed-source provenance (2026-10-19)
- [x] Native monitoring configured; prompt ingestion verified (2026-10-16), hosted-v6 model/tool correlation and observed model usage verified by read-only query (2026-10-20; no new invocation)
- [ ] Refresh correct tenant/subscription, source pins, model version, retained artifacts and actual three-presenter access before rehearsal
- [ ] Agree exact demo version/request; resolve candidate-7 session/outer-version discrepancy before treating it as candidate execution proof
- [ ] Prepare the retained hosted trace lookup for the presentation; portal UI and all-presenter access still need verification
- [ ] Demonstrate the full five-case good/bad evaluation gate, or clearly label the unverified showcase
- [x] Real approved wiki write and Teams delivery demonstrated on v13 by P1 (2026-10-20, [evidence](../../src/agents/documentation-agent/TEAMS_APPROVAL.md)); assessment stays read-only. Second-user Teams test pending ([#31](https://github.com/wdhm/foundry-agentic-pattern/issues/31))
- [x] P2 40-minute presenter run order, fallbacks and evidence prepared ([guide](p2-presenter-guide.md)); live PR #62 assessment still to be rehearsed
- [ ] Obtain separate routing approval and demonstrate timed rollback with new named-path sessions; two deployed versions or a pin alone do not pass
- [x] P3 primary evidence content, AI Gateway explanatory fallback and 40-minute presenter run order prepared; four existing next-step slides retained
- [ ] Assemble the source slides into the shared deck and review story, visual layout, evidence dates and captures with all presenters
- [ ] Run the 09:00-12:00 agenda with all presenters, record timings and fix issues found ([#40](https://github.com/wdhm/foundry-agentic-pattern/issues/40))
- [ ] Record a reviewed fictional-data backup and its location; no credentials or unrestricted source-bearing responses
