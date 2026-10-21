# P2 presenter guide: knowledge, tools and identity

**Owner:** Rickard (P2). **Slot:** 10:30-11:10, 40 minutes, matching the [agenda](agenda.md). **Prepared:** 2026-10-21. John (P1) owns shared-deck assembly. This is a timed run order with fallbacks, not a completed rehearsal.

**Storyline:** *where the agent's facts come from, and who it is when it reads and writes them.* Stable rules come from Foundry IQ, live facts come through a versioned toolbox, and every read and write runs as the agent's own identity. John's block already showed the hosted agent, the output contract and the Teams approval card; this block opens the hood on the sources and the identity behind them.

**Recorded runtime (2026-10-21):** hosted `documentation-agent:13` serves 100%. Assessment uses toolbox `documentation-agent-readonly:1`; only the approval runtime uses `documentation-agent-write:1` (`ado___wiki_upsert_page` only). Re-check serving before delivery; if it changed, update this line rather than presenting stale versions.

## Slides

[`slides/p2-knowledge-identity.pptx`](slides/p2-knowledge-identity.pptx): five slides, one per topic, each with speaker notes. Slides 2–4 end in a **LIVE DEMO** bar that names the command or view to switch to. Keep each slide up for under a minute, then demo.

## Run order and hard stops

| Time | Minutes | Slide → demo | Fallback / stop point |
|---|---|---|---|
| 10:30-10:32 | 2 | **Framing** (slide 1). One sentence on data: *everything runs on a fictional Order Sync integration with three planted drifts, so we can show real calls safely* ([data](../../data/README.md)). | Slide only |
| 10:32-10:45 | 13 | **Foundry IQ (F3)** (slide 2). Run `demo-foundry-iq.ps1`: the knowledge base returns DS-14 Error handling and DS-30 Drift as references. Then in the Foundry portal open knowledge base `kb-doc-agent` → source `ks-doc-knowledge` → index `doc-knowledge`, and the MCP connection `kb-doc-agent-mcp` (project managed identity). Close on *stable rules are indexed; code, wiki and work items are read live* ([guide](foundry-iq-guide.md), [ADR 0011](../adr/0011-knowledge-foundry-iq-and-toolbox.md)) | Show the [standard](../../data/knowledge/documentation-standard.md) and the guide's diagram. Do not re-index or change the knowledge base live |
| 10:45-10:58 | 13 | **Toolbox (F1)** (slide 3). Run `demo-toolbox.ps1`: `documentation-agent-readonly` (four read tools over three connections) next to `documentation-agent-write` (one tool). Show the same in the Foundry portal. Then the PR #62 assessment → `gaps_found` with pinned evidence and findings citing DS-30 | Assessment live only if it passed at rehearsal (see below). Otherwise the recorded result ([GitHub guide](github-mcp-guide.md#the-result), [gate evidence](evaluation-release-guide.md#live-gate-evidence-2026-10-20)). Never enable write tools in an assessment |
| 10:58-11:06 | 8 | **Agent identity** (slide 4). Run `demo-toolbox.ps1 -TryAsMe`: Foundry IQ and GitHub answer, but ADO refuses a person because the connection only accepts the agent's identity. In Entra Agent ID show the agent identity and the agent user. Open the wiki history of `/Workshop/Approval-Sandbox`: John's Teams Approve commit is authored by **documentation-agent (agent user)** ([guide](agent-identity-guide.md), [identity table](resource-organization-guide.md#identities-who-authenticates-where)) | Use the slide's table. Wiki history is a read; no new write. Name the security debt below |
| 11:06-11:10 | 4 | **Agent 365** (slide 5): registry, access, security, lifecycle ([source](slides/agent-365.md), [#46](https://github.com/wdhm/foundry-agentic-pattern/issues/46)). Hand over to Louise | Slide only |

Total: **2 + 13 + 13 + 8 + 4 = 40 minutes**. Keep questions for the shared 11:50 Q&A. If a view fails, switch to its fallback at once; do not debug access on stage.

**Backup slides, only if asked:** [Work IQ](slides/work-iq.md) ([#47](https://github.com/wdhm/foundry-agentic-pattern/issues/47)) and [PDF/SharePoint sources](slides/document-sources.md) ([#48](https://github.com/wdhm/foundry-agentic-pattern/issues/48)).

## Set up the showcase

Do this the day before and again 30 minutes before the slot. Every step is read-only.

1. **Sign in** with `az login` as the tenant admin (the scripts use `az account get-access-token`).
2. **Foundry IQ script:** `./infra/scripts/demo-foundry-iq.ps1 -SearchService srch-foundry-agentic-r8n3ld`. Pass: DS-14 and DS-30 among the references. Use `-Query "..."` to ask a different question live.
3. **Toolbox script:** `./infra/scripts/demo-toolbox.ps1 -ProjectEndpoint https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic`, then again with `-TryAsMe`. Pass: two toolboxes listed; with `-TryAsMe`, the ADO source is refused (`-32007`, `AgenticIdentityToken`).
4. **Browser tabs**, in demo order:
   - [Foundry portal](https://ai.azure.com) → project `proj-agentic` → knowledge base `kb-doc-agent`, then the two toolboxes.
   - [Microsoft Entra admin center](https://entra.microsoft.com) → Agent ID → the `documentation-agent` agent identity, and Users → `documentation-agent@…` (the agent user).
   - [Wiki page `/Workshop/Approval-Sandbox`](https://dev.azure.com/foundry-agentic/integration-team/_wiki/wikis/integration-team.wiki?pagePath=/Workshop/Approval-Sandbox) → History. Commits `d3ddedec71` (Teams Approve, 2026-10-20) and `ca622ad0cf` are by the agent user.
   - [PR #62](https://github.com/wdhm/foundry-agentic-pattern/pull/62) and the recorded fallback result.
5. **Rehearse the PR #62 assessment** once (next section) and record the run and session IDs.
6. **Open the deck** in presenter view; the notes hold the talk track.
## Live assessment: rehearse first

The live toolbox demo is one read-only assessment of PR #62 on the serving version. It is allowed live only if the same request passed at the rehearsal on the same serving version:

- **Request:** [`examples/assessment-request.json`](../../src/agents/documentation-agent/examples/assessment-request.json) (GitHub, PR #62) with fresh request/correlation IDs. The Azure Repos variant is [`azure-repos-request.json`](../../src/agents/documentation-agent/examples/azure-repos-request.json).
- **Path:** the hosted CLI ([guide](cli-trigger-guide.md)) or the Foundry portal, whichever passed at rehearsal. The CLI needs a reviewed artifact JSON for the serving version; v13 was built from a working tree, so confirm with John that its provenance check passes before relying on it.
- **Pass:** `gaps_found`; findings cover retry/backoff, ERP timeout and dead-letter queue; Git evidence at `ad623147fbb1eeb9a6423d437df199c91db15a9e`; no write tool called.
- **Cost:** each run creates a session and uses model/tool calls. Record the run and session IDs at rehearsal.

## Evidence to have ready without making new calls

| Prepared item | Exact allowed interpretation |
|---|---|
| [Toolbox and identity inventory](../setup.md#agent-identity-and-azure-devops) | Recorded toolboxes, connections, agent user, consent scopes and gateway role. Not a live permission audit |
| [Live gate evidence](evaluation-release-guide.md#live-gate-evidence-2026-10-20) | Five cases ran live on isolated candidates with real toolbox reads; `order-sync-retry` scored 5/1/5. Not a v13 run |
| [Teams approval evidence](../../src/agents/documentation-agent/TEAMS_APPROVAL.md) | Approve on v13 wrote the exact approved page as the agent user (2026-10-20, run `9768b3ac…`). One sandbox page, no ETag protection |
| [GitHub guide result](github-mcp-guide.md#the-result) | Historical prompt-agent run (2026-10-14) showing the same tool order and pinned SHA. Not hosted evidence |

## Security debt to say out loud

Simplicity first, hardening last ([next steps §9](../next-steps.md#9-production-hardening-out-of-mvp-scope)):

- The approval write path reuses the hosted agent user, now **Basic + Contributors** with `wiki.write`, and the gateway is no longer read-only. Protection rests on the toolbox allowlist and the approval runtime, not on identity ([#22](https://github.com/wdhm/foundry-agentic-pattern/issues/22)).
- GitHub uses a fine-grained token in a project connection; production should use a GitHub App or OAuth passthrough.
- Wiki writes have no ETag protection.

## Presenter handoff and outstanding work

- **Before rehearsal:** confirm serving version, run the live assessment once and record IDs, open all tabs (GitHub PR #62, ADO wiki + history, work item 1, Foundry portal toolboxes, Entra Agent ID), and verify presenter access to each.
- **Teams:** the Teams card is John's demo. The app is now installed for everyone in the tenant (2026-10-21); propagation can take up to 24 hours. A second-user Teams test is tracked on [#31](https://github.com/wdhm/foundry-agentic-pattern/issues/31).
- **Shared deck:** John copies the slide sources into the deck ([#39](https://github.com/wdhm/foundry-agentic-pattern/issues/39)); all three rehearse ([#40](https://github.com/wdhm/foundry-agentic-pattern/issues/40)).
