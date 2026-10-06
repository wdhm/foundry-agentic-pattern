# Workshop agenda: Agentic Pattern on Microsoft Foundry

**Format:** half day (09:00–12:00), **demo-driven**, run against a **pre-deployed environment in a shared tenant** ([ADR 0002](../adr/0002-workshop-format.md)).
**Audience:** customer architects and technical decision makers ([ADR 0001](../adr/0001-audience-and-delivery.md)).
**Take-away:** this repository. Fork it privately, plug in your own sources and documentation standard, and run `azd up`.

**Presenters**
- **P1**: Agent architecture (hosted agent, contract, state, Teams HITL)
- **P2**: Knowledge & identity (Foundry IQ, Toolbox/MCP, Agent ID, RBAC, mock data)
- **P3**: AgentOps & platform (infra/azd, AI Gateway/FinOps, evals, CI/CD, rollback, tracing)

| Time | Block | Lead | Demo / content |
|---|---|---|---|
| 09:00–09:15 | **Welcome & framing**: why a *pattern*, not just an agent | P1 | Problem statement, the Documentation Agent story, what you take home |
| 09:15–09:45 | **Live end-to-end demo** | P1 | PR on the sample integration → `AgentResult` → Teams approval → wiki updated |
| 09:45–10:15 | **Agent architecture & contract** | P1 | Hosted agent on Agent Framework, `AgentRequest`/`AgentResult`, "Information missing", Cosmos DB audit record |
| 10:15–10:30 | ☕ Break | | |
| 10:30–11:00 | **Knowledge & identity** | P2 | Foundry IQ vs. Toolbox live calls, evidence at exact versions, Agent ID and least privilege, approval-gated write |
| 11:00–11:35 | **AgentOps & platform** | P3 | `azd up`, traces in App Insights, AI Gateway limits + cost per agent, eval gate blocking a bad version, rollback via `version_selector` |
| 11:35–11:50 | **Beyond v1** | All | A2A Publisher agent, landing zone & vending, Agent 365, Work IQ, deployment strategy ([next-steps](../next-steps.md)) |
| 11:50–12:00 | **Fork & adapt + Q&A** | All | How to adapt the repo; next steps with your team |

## Demo checklist (pre-workshop)
- [ ] Environment deployed with `azd up` in the shared tenant (Sweden Central)
- [ ] Mock data seeded (wiki, work items, ADRs, documentation standard)
- [ ] Agent published to Teams; presenters have access
- [ ] A prepared PR with planted gaps ready to open live
- [ ] A prepared "bad" agent version that fails the eval gate
- [ ] Two agent versions deployed for the rollback demo
- [ ] Backup recording of the end-to-end demo
