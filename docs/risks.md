# Risks

Verified risks and open questions for Agentic Pattern v1. Each risk has a status, the evidence for it, a mitigation and a linked spike in milestone [**M0: Spikes**](https://github.com/wdhm/foundry-agentic-pattern/milestone/1).

| ID | Topic | Status | Owner | ADRs | Spike |
|---|---|---|---|---|---|
| [R1](#r1) | Tool approval enforcement and approval UX in Teams | 🟡 Partly verified, spike needed | P1 · John | [0008](adr/0008-human-in-the-loop-approval.md), [0009](adr/0009-hosted-agent-runtime.md), [0016](adr/0016-state-and-audit-cosmos-db.md) | [#1](https://github.com/wdhm/foundry-agentic-pattern/issues/1) |
| [R2](#r2) | Publish hosted agent to Teams, and rollback via `version_selector` | 🟢 OK (verify in spike) | P3 · Louise | [0008](adr/0008-human-in-the-loop-approval.md), [0009](adr/0009-hosted-agent-runtime.md), [0013](adr/0013-evaluation-gate-in-ci.md), [0018](adr/0018-region-sweden-central.md) | [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4) |
| [R3](#r3) | Agent identity lifecycle and Azure DevOps access | 🟠 Spike needed | P2 · Rickard | [0012](adr/0012-agent-identity-and-rbac.md), [0014](adr/0014-infrastructure-scope.md) | [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2) |
| [R4](#r4) | AI Gateway token limits and per-agent cost attribution | 🟡 Design adjusted | P3 · Louise | [0014](adr/0014-infrastructure-scope.md) | [#3](https://github.com/wdhm/foundry-agentic-pattern/issues/3) |

---

<a id="r1"></a>
## R1: Tool approval enforcement and approval UX in Teams

**Status:** 🟡 Partly verified. Spike needed for the Teams approval UX.

**Findings**
- The Toolbox MCP endpoint does **not** block `tools/call` when `require_approval: always` is set. The **hosted agent runtime** must pause, collect the approval decision, and then resume or reject **that exact tool call**.
  Source: [Use a toolbox from a hosted agent: enforce tool approval](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent#enforce-tool-approval)
- Agents published to Microsoft 365 / Teams do **not** support streaming or citations. Evidence must be rendered in the message body.
  Source: [Publish to Microsoft 365 Copilot and Teams: limitations](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network#limitations)

**Impact:** without explicit runtime enforcement, an approval-gated write could run without approval. Evidence links would also be lost in Teams if we relied on native citations.

**Mitigation**
- The hosted agent implements an explicit approval interrupt. Pending tool calls (tool name, arguments hash, run ID) are persisted in Cosmos DB, and the call executes **only** when an approval matching that exact call is received ([ADR 0016](adr/0016-state-and-audit-cosmos-db.md)).
- Evidence is rendered inline in the Teams message body as a compact list with exact versions.

**Spike (M0, [#1](https://github.com/wdhm/foundry-agentic-pattern/issues/1)):** demonstrate Approve / Modify / Reject in Teams for a hosted agent, with the wiki-write call executed only after approval.

---

<a id="r2"></a>
## R2: Publish hosted agent to Teams, and rollback via `version_selector`

**Status:** 🟢 OK based on documentation. Verify end to end in a spike.

**Findings**
- An agent can be published to Teams via the portal or REST. This requires **Azure Bot Service Contributor** + **Foundry User**. The **"Just you"** scope needs no admin approval, which suits the demo.
- Hosted agents are available in **Sweden Central**.
- The agent endpoint's `version_selector` with `traffic_percentage` provides native **rollback/canary without republishing**.
  Source: [Publish agents to Microsoft 365 Copilot and Teams](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot)

**Mitigation / design use:** the CI eval gate promotes a new version by shifting `traffic_percentage`. A failed gate means no shift, and a rollback shifts traffic back ([ADR 0013](adr/0013-evaluation-gate-in-ci.md)).

**Spike (M0, [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4)):** publish a hosted agent to Teams in Sweden Central, run two versions, and shift traffic back and forth without republishing.

---

<a id="r3"></a>
## R3: Agent identity lifecycle and Azure DevOps access

**Status:** 🟠 Spike needed.

**Findings**
- A hosted agent gets its **own agent identity** (Entra Agent ID).
- **Publishing creates a new agent identity**, so role assignments must be repeated. They can only be made **after** the agent exists, which rules out upfront Bicep and requires a **post-deploy CI step**.
- Azure DevOps supports Entra service principals and managed identities. Whether it accepts **agent-identity service principals** is **not explicitly documented**.
  Source: [Agent identity concepts](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity)

**Impact:** if Azure DevOps rejects agent-identity SPs, wiki write and work item read cannot use the agent's own identity.

**Mitigation / fallback**
- Post-deploy RBAC workflow (`post-deploy-rbac.yml`) that runs after create/publish.
- Fallback: authenticate the Toolbox connection with the **project managed identity** or a **user-assigned managed identity**, and keep the approver and run ID in the audit trail and the wiki commit message ([ADR 0012](adr/0012-agent-identity-and-rbac.md)).

**Spike (M0, [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2)):** agent identity → Azure DevOps (read work items, read/write wiki). Record go/no-go and the chosen fallback.

---

<a id="r4"></a>
## R4: AI Gateway token limits and per-agent cost attribution

**Status:** 🟡 Design adjusted.

**Findings**
- AI Gateway token limits and quotas apply **per project + model deployment**, **not per agent**.
  Source: [Enforce token limits for models](https://learn.microsoft.com/azure/foundry/control-plane/how-to-enforce-limits-models)

**Impact:** "budget per agent" cannot be enforced natively at the gateway.

**Mitigation / design use**
- Enforce limits per project/deployment.
- **Cost per agent/version** is handled by a **FinOps pattern**: model calls are tagged (agent name, agent version, run ID) and token usage is aggregated from APIM logs and Application Insights.

**Spike (M0, [#3](https://github.com/wdhm/foundry-agentic-pattern/issues/3)):** configure a token limit on a deployment through the AI Gateway, emit tagged calls from two agent versions, and produce a cost-per-agent/version query.
