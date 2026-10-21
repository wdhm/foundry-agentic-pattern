# Risks

Verified risks and open questions for Agentic Pattern v1. Each risk has a status, the evidence for it, a mitigation and a linked spike in milestone [**M0: Spikes**](https://github.com/wdhm/foundry-agentic-pattern/milestone/1).

| ID | Topic | Status | Owner | ADRs | Spike |
|---|---|---|---|---|---|
| [R1](#r1) | Tool approval enforcement and approval UX in Teams | 🟢 Go for MVP: native Activity cards and runtime enforcement | P1 · John | [0008](adr/0008-human-in-the-loop-approval.md), [0009](adr/0009-hosted-agent-runtime.md), [0016](adr/0016-state-and-audit-cosmos-db.md) | [#1](https://github.com/wdhm/foundry-agentic-pattern/issues/1) |
| [R2](#r2) | Publish to Teams and roll back a pinned agent version | 🟡 Serving pin recorded; candidate evidence/channel/rollback proof open | P3 · Louise | [0008](adr/0008-human-in-the-loop-approval.md), [0009](adr/0009-hosted-agent-runtime.md), [0013](adr/0013-evaluation-gate-in-ci.md), [0018](adr/0018-region-sweden-central.md) | [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4) |
| [R3](#r3) | Agent identity lifecycle and Azure DevOps access | 🟢 Go: agent user + gateway ([ADR 0021](adr/0021-agent-user-and-ado-mcp-gateway.md)); onboarding scripted, CI open | P2 · Rickard | [0012](adr/0012-agent-identity-and-rbac.md), [0014](adr/0014-infrastructure-scope.md), [0021](adr/0021-agent-user-and-ado-mcp-gateway.md) | [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2) |
| [R4](#r4) | AI Gateway token limits and per-agent cost attribution | 🟡 Design adjusted | P3 · Louise | [0014](adr/0014-infrastructure-scope.md) | [#3](https://github.com/wdhm/foundry-agentic-pattern/issues/3) |

---

<a id="r1"></a>
## R1: Tool approval enforcement and approval UX in Teams

**MVP decision (2026-10-20): Go with native Activity Adaptive Cards.**
The Responses-to-Teams bridge displayed the preview but not decision buttons.
The Activity handler merged in [PR #94](https://github.com/wdhm/foundry-agentic-pattern/pull/94)
reuses the #15 approval engine and SDK state store inside the same hosted app.
On served v13, the user verified card delivery, Reject, stale-decision rejection,
Modify with new pending ID/content, invalidation of the original proposal and
Approve with a success card. An independent ADO readback confirmed exactly the
approved sandbox page content. See the
[Teams guide and dated evidence](../src/agents/documentation-agent/TEAMS_APPROVAL.md#live-teams-evidence-2026-10-20).
Assessment versions retain application-level read guards; P2's shared gateway
and identity now permit writes, so gateway-level read-only isolation is not claimed.

**Earlier local spike (2026-10-16):** the
[hosted native-approval experiment](workshop/hosted-approval-spike.md) exercises
Approve / Reject and explicit Modify through the Responses protocol. It persists
the exact pending call and a dummy receipt with SDK state storage, and rejects
tampered, replayed and superseded decisions. This is a local dummy-target result,
not a Toolbox integration or Teams verification by itself. The subsequent live
Teams result above establishes the MVP go/no-go outcome.

**Status:** 🟢 MVP verified and documented. Production hardening remains deferred.

**Findings**
- The Toolbox MCP endpoint does **not** block `tools/call` when `require_approval: always` is set. The **hosted agent runtime** must pause, collect the approval decision, and then resume or reject **that exact tool call**.
  Source: [Use a toolbox from a hosted agent: enforce tool approval](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent#enforce-tool-approval)
- Agents published to Microsoft 365 / Teams do **not** support streaming or citations. Evidence must be rendered in the message body.
  Source: [Publish to Microsoft 365 Copilot and Teams: limitations](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network#limitations)

**Impact:** without explicit runtime enforcement, an approval-gated write could run without approval. Evidence links would also be lost in Teams if we relied on native citations.

**Mitigation**
- The hosted approval runtime executes only a matching approved call. Native Teams decisions are checked against the saved tenant/user/conversation/session binding, then delegated to the same hash/policy/ETag-claim checks as Responses. Cosmos DB is deferred under [ADR 0022](adr/0022-mvp-scope-platform-first.md), not an implemented MVP dependency.
- Evidence is rendered inline in the Teams message body as a compact list with exact versions.

**Scope limits:** Reject/Modify results are user-observed live UI evidence plus
automated runtime tests; no independent live gateway call-count audit is claimed.
The approved write has independent page readback, not a distributed exactly-once
guarantee. Wiki ETag concurrency, full audit/commit-message attribution and
automated PR-to-Teams posting remain follow-ups. Live client screenshots and
mobile-specific checks are workshop packaging, not evidence already collected.
The demo used an explicitly approved sandbox and no-concurrent-editor agreement.

---

<a id="r2"></a>
## R2: Publish to Teams and roll back a pinned agent version

**Status:** 🟡 Partial. P1 recorded an approved concrete version-6 serving pin,
fresh named-path baseline and isolated version-7 deployment on 2026-10-19.
Teams delivery, promotion and timed rollback remain unverified. See the
[current dated record](setup.md#recorded-hosted-serving-and-candidate-state-2026-10-19)
and [release/rollback runbook](workshop/release-rollback-guide.md) for contracts,
historical snapshots and approval boundaries.

**Findings**
- Current documentation supports publishing the stable agent endpoint via portal or `POST /agents/{name}/microsoft365/publish?api-version=v1`. **Foundry User** plus Bot resource/channel write permissions are required; **Azure Bot Service Contributor Role**, Contributor or Owner covers the Bot side. **"Just you"** maps to REST `Shared` / `BotServiceRbac`, without publication admin approval; tenant policies and caller RBAC still apply.
  Sources: [Portal publishing](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot), [REST publishing](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).
- Hosted availability includes **Sweden Central**. The October-16 stub/latest snapshot is historical: the October-19 record has hosted serving `6` at 100%, active unpromoted candidate `7`, and no demonstrated Teams publication.
- P1 reports candidate session GET `version_ref=7` but outer Responses `agent_reference.version=6`. The CLI preserves both and fails on disagreement. This is not sufficient candidate-version evidence for a release; do not promote to make an evidence check pass.
- `PATCH /agents/{name}?api-version=v1` selects a concrete version using `agent_endpoint.version_selector.version_selection_rules`, one `FixedRatio` rule and `traffic_percentage: 100`. This is documented rollback without channel republishing, not live proof. The [hosted management guide](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent#configure-agent-endpoint-routing) explicitly disallows traffic splitting, conflicting with the [azd canary example](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-production#roll-out-a-production-version-gradually); do not assume 50/50 support.

**Mitigation / design use:** pin and verify the concrete good serving version **before** creating a candidate; default latest routing can otherwise expose a failed-eval version. Evaluate the exact candidate, then promote it at 100% only on pass and approval. A failed gate prevents promotion; rollback restores the retained good selector and verifies a fresh session. Existing hosted sessions do not migrate on selector changes. This refines the routing assumption in [ADR 0013](adr/0013-evaluation-gate-in-ci.md) without claiming its live acceptance criteria are met.

**Remaining spike ([#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4)):** preserve the recorded serving pin, resolve candidate execution evidence, then separately approve and prove promotion/rollback, Bot/channel publication, Teams delivery and identity credential survival. Canary needs Microsoft clarification. [#34](https://github.com/wdhm/foundry-agentic-pattern/issues/34)'s full live rollback in under two minutes is still unverified.

---

<a id="r3"></a>
## R3: Agent identity lifecycle and Azure DevOps access

**Status:** 🟢 Go (spike done, 2026-10-08). Per-agent onboarding is automated ([`onboard-agent.ps1`](../infra/scripts/onboard-agent.ps1)).

**Findings**
- Every new-model agent gets its **own agent identity and blueprint** when it is created. New versions keep the same identity. According to Learn, publishing to Microsoft 365 / Teams does not change it either. Legacy agents use the shared project identity, and the legacy *Agent Application* publish flow creates a distinct identity.
  Sources: [Agent identity concepts](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity), [Agent types during the transition](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications#agent-types-during-the-transition)
- Role assignments can only be made **after** the agent exists, which rules out upfront Bicep. They run as a post-deploy step: `infra/scripts/onboard-agent.ps1`, which is idempotent.
- **Spike result:** Azure DevOps **rejects agent identity tokens**, both on REST and on the [remote Azure DevOps MCP server](https://learn.microsoft.com/azure/devops/mcp-server/remote-mcp-server). The error is *"Identity … is currently Deleted"*.
- Azure DevOps **accepts the agent's user account** (agent user). Its token comes from the [agent user OAuth flow](https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow), secretless via a user-assigned managed identity as a blueprint credential.
- End to end, verified: Foundry agent → gateway → remote Azure DevOps MCP server. The agent read a work item and updated a wiki page after approval. The commit author is `doc-agent-spike (agent user)`.
  Details: [workshop guide](workshop/agent-identity-guide.md).

**Decision:** [ADR 0021](adr/0021-agent-user-and-ado-mcp-gateway.md): agent user + thin gateway to Microsoft's remote Azure DevOps MCP server.

**Remaining risk**
- Each new agent needs a new agent user, a consent grant, an app role assignment and gateway settings. `onboard-agent.ps1` does this; manual onboarding is the accepted MVP. CI wiring ([#28](https://github.com/wdhm/foundry-agentic-pattern/issues/28)) is deferred, not a current release prerequisite.
- The gateway serves one agent at a time; onboarding re-points it.
- Our federated credential on the Foundry-managed blueprint survives new versions. Whether it survives Microsoft 365 / Teams publishing is not verified yet ([#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4)).
- Security debt:
  - the retained prompt user has Basic + Contributors; the hosted assessment now uses Stakeholder + Readers and read-only consent;
  - public gateway ingress;
  - per-scope enforcement on the remote MCP server is unverified.

**Spike (M0, [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2)):** done. Go with the agent user, as above.

---

<a id="r4"></a>
## R4: AI Gateway token limits and per-agent cost attribution

**Status:** 🟡 Explanatory slides chosen under accepted ADR 0022. The
[two-slide fallback](workshop/slides/ai-gateway.md) and
[presenter run order](workshop/p3-presenter-guide.md) are prepared. No live
token-limit/429 or per-agent cost proof is recorded; full APIM FinOps
attribution remains future hardening.

**Opt-in repository increment (2026-10-21):** the user reopened gateway work.
[ADR 0027](adr/0027-opt-in-ai-gateway.md) and the
[integration guide](ai-gateway.md) add model/read-toolbox routing and reviewed
APIM configuration. Direct mode remains the default. No live routes, grants or
deployments were changed; agent ingress, approved writes and service-side
evaluators are not covered by these opt-ins. The earlier slide disposition is
historical; no live enforcement or per-agent billing proof follows from this code.

**Findings**
- AI Gateway token limits and quotas apply **per project + model deployment**, **not per agent**.
  Source: [Enforce token limits for models](https://learn.microsoft.com/azure/foundry/control-plane/how-to-enforce-limits-models)

**Impact:** "budget per agent" cannot be enforced natively at the gateway.

**Mitigation / design use**
- Proposed enforcement is per project/deployment, not a demonstrated per-agent budget.
- Proposed **cost per agent/version** uses a **FinOps pattern**: trusted agent/version/run correlation, layer-specific model usage and billing reconciliation. Native token observations are not a validated cost ledger or proof that calls traversed APIM.

**Disposition ([#3](https://github.com/wdhm/foundry-agentic-pattern/issues/3),
[#23](https://github.com/wdhm/foundry-agentic-pattern/issues/23)):** the accepted
MVP uses dedicated slide coverage; the live limits/tagged-call/cost-query spike
is deferred. Shared-deck assembly and presenter review remain open. Slide
preparation is not proof of a built gateway capability and does not authorize
APIM provisioning or billable test calls.
