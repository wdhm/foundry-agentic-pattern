# P2 presenter guide: knowledge, tools and identity

**Owner:** Rickard (P2). **Slot:** 10:30-11:10, 40 minutes, matching the [agenda](agenda.md). **Prepared:** 2026-10-21. John (P1) owns shared-deck assembly. This is a timed run order with fallbacks, not a completed rehearsal.

**Storyline:** *where the agent's facts come from, and who it is when it reads and writes them.* Stable rules come from Foundry IQ, live facts come through a versioned toolbox, and every read and write runs as the agent's own identity. John's block already showed the hosted agent, the output contract and the Teams approval card; this block opens the hood on the sources and the identity behind them.

**Recorded runtime (2026-10-21):** hosted `documentation-agent:13` serves 100%. Assessment uses toolbox `documentation-agent-readonly:1`; only the approval runtime uses `documentation-agent-write:1` (`ado___wiki_upsert_page` only). Re-check serving before delivery; if it changed, update this line rather than presenting stale versions.

## Run order and hard stops

| Time | Minutes | Material and speaking sequence | Fallback / stop point |
|---|---|---|---|
| 10:30-10:35 | 5 | **Mock data (F8).** 1 min: fictional Order Sync (webshop → Fabrikam ERP) in [`samples/sample-integration`](../../samples/sample-integration/README.md). 2 min: [PR #62](https://github.com/wdhm/foundry-agentic-pattern/pull/62) diff (retry/backoff, `erp.timeoutSeconds`, dead-letter queue). 2 min: the drifted wiki page `/Order Sync/Overview` and work item 1, then the three planted drifts in [`data/`](../../data/README.md#contents) | Browser tabs only; no agent call. If ADO is slow, show the planted-gaps row in [`data/`](../../data/README.md#contents) |
| 10:35-10:43 | 8 | **Foundry IQ (F3).** 2 min: [documentation standard](../../data/knowledge/documentation-standard.md) and its `DS-xx` rule IDs. 3 min: knowledge base `kb-doc-agent` → source `ks-doc-knowledge` → index `doc-knowledge`, reached as an MCP tool over the project-MI connection `kb-doc-agent-mcp`. 3 min: why stable rules are indexed but wiki/work items are read live ([guide](foundry-iq-guide.md), [ADR 0011](../adr/0011-knowledge-foundry-iq-and-toolbox.md)) | Use the guide's diagram and design-choice table. Do not re-index or change the knowledge base live |
| 10:43-10:55 | 12 | **Toolbox (F1), main demo.** 3 min: in the Foundry portal show `documentation-agent-readonly` (four read tools over `kb-doc-agent-mcp`, `github-mcp`, `ado-mcp-proxy`) next to `documentation-agent-write` (one tool). 2 min: GitHub over the hosted read-only MCP server with a fine-grained token ([guide](github-mcp-guide.md)). 5 min: one assessment of PR #62 → `gaps_found`, every evidence item pinned (commit `ad623147…`, wiki ETag, work-item revision) and findings citing DS-30. 2 min: the same reads also work from Azure Repos ([#93](https://github.com/wdhm/foundry-agentic-pattern/pull/93), [guide](azure-devops-workflow-guide.md)) | Live only if the rehearsal run passed (see below). Otherwise show the recorded result in the [GitHub guide](github-mcp-guide.md#the-result) and the live gate row `order-sync-retry 5/1/5` ([evidence](evaluation-release-guide.md#live-gate-evidence-2026-10-20)). Never enable write tools in an assessment |
| 10:55-11:03 | 8 | **Identity & resource organisation.** 3 min: Entra **Agent ID**: the hosted agent's identity and its agent user `documentation-agent@…`; the token chain MI → blueprint → agent identity → agent user ([guide](agent-identity-guide.md)). 2 min: *the connection decides which identity is presented* ([table](resource-organization-guide.md#identities-who-authenticates-where)). 3 min: ADO wiki history of `/Workshop/Approval-Sandbox`: the commit from John's Teams Approve is authored by **documentation-agent (agent user)**, not a person | Wiki history is a read; no new write. If Entra is slow, use the identity table. Name the security debt below honestly |
| 11:03-11:10 | 7 | **Slides:** [Agent 365](slides/agent-365.md) (fleet governance, [#46](https://github.com/wdhm/foundry-agentic-pattern/issues/46)), [Work IQ](slides/work-iq.md) ([#47](https://github.com/wdhm/foundry-agentic-pattern/issues/47)), [document sources](slides/document-sources.md) (PDF/SharePoint, [#48](https://github.com/wdhm/foundry-agentic-pattern/issues/48)). About 2 minutes each, 1 minute hand-over to Louise | Slides only |

Total: **5 + 8 + 12 + 8 + 7 = 40 minutes**. Keep questions for the shared 11:50 Q&A. If a view fails, switch to its fallback at once; do not debug access on stage.

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
