# P2 presenter guide: knowledge, tools and identity

**Owner:** Rickard (P2). **Slot:** 10:30-11:10, 40 minutes, matching the [agenda](agenda.md). **Prepared:** 2026-10-21. John (P1) owns shared-deck assembly. This is a timed run order with fallbacks, not a completed rehearsal.

**Storyline:** *where the agent's facts come from, and who it is when it reads and writes them.* Stable rules come from Foundry IQ, live facts come through a versioned toolbox, and every read and write runs as the agent's own identity. John's block already showed the hosted agent, the output contract and the Teams approval card; this block opens the hood on the sources and the identity behind them.

**Recorded runtime (2026-10-23):** hosted `documentation-agent:29` serves with read-only chat enabled. Chat and assessment read through toolbox `documentation-agent-readonly`; only the approval runtime uses `documentation-agent-write:1` (`ado___wiki_upsert_page` only). Chat may read only the sources in [`order-sync-chat-sources.json`](../../src/agents/documentation-agent/approval/order-sync-chat-sources.json): the Order Sync repo at commit `97990d1`, wiki page `/Order Sync/Overview` and work item 1. Re-check serving before delivery; if it changed, update this line rather than presenting stale versions.

## Slides

[`slides/p2-knowledge-identity.pptx`](slides/p2-knowledge-identity.pptx): five slides, one per topic, each with speaker notes. Slides 2–4 end in a **LIVE DEMO** bar that names the command or view to switch to. Keep each slide up for under a minute, then demo.

## Run order and hard stops

| Time | Minutes | Slide → demo | Fallback / stop point |
|---|---|---|---|
| 10:30-10:32 | 2 | **Framing** (slide 1). One sentence on data: *everything runs on a fictional Order Sync integration with three planted drifts, so we can show real calls safely* ([data](../../data/README.md)). | Slide only |
| 10:32-10:45 | 13 | **Foundry IQ (F3)** (slide 2). In the playground of `documentation-agent` ask: *"What does our documentation standard require for error handling and for drift between code and docs? Cite the rule IDs."* The answer cites DS-14, DS-30 and DS-31 with links to the standard. **Proof:** Agents → **Traces** → the newest trace → span `execute_tool knowledge___knowledge_base_retrieve`. Then Knowledge → Knowledge bases → `kb-doc-agent` → source `ks-doc-knowledge` → index `doc-knowledge`, and find DS-14. Close on *stable rules are indexed once and cited every time* ([guide](foundry-iq-guide.md), [ADR 0011](../adr/0011-knowledge-foundry-iq-and-toolbox.md)) | Show the [standard](../../data/knowledge/documentation-standard.md) and the guide's diagram. Do not re-index or change the knowledge base live |
| 10:45-10:58 | 13 | **Toolbox (F1)** (slide 3). New chat: *"Compare the Order Sync code and config with the wiki page /Order Sync/Overview and work item 1. Which rules in our documentation standard does the wiki not cover yet? Cite rule IDs and where each fact comes from."* The answer is a gap table per rule (DS-11, DS-13, DS-14, DS-15, DS-16, DS-17) with links to the README and `settings.json` at the pinned commit, the wiki page and the work item: four sources, one toolbox. **Proof:** Agents → **Traces** → the newest trace: `tools/list documentation-agent-readonly:2` (toolbox and version), then `execute_tool ado___repo_file`, `ado___wiki`, `ado___wit_work_item` and `knowledge___knowledge_base_retrieve`. Show the toolbox definitions (`documentation-agent-readonly`: knowledge, GitHub, ADO; `documentation-agent-write`: one tool, behind Teams approval) in VS Code → Foundry Toolkit → Toolboxes | Open the wiki page and the standard side by side. Do not edit toolboxes live |
| 10:58-11:06 | 8 | **Agent identity** (slide 4). Same chat: *"Looks good. Update the wiki page /Order Sync/Overview with these gaps now, I approve."* The agent refuses: publishing needs the Approve button on the Teams review card. **Proof of who read ADO:** Azure portal → Container App `ca-doc-agent-mcp` → Log stream: each ADO call logs `authorized caller oid=ea9e8fb5-…`. In Entra → Agent ID, the same id is `…-documentation-agent-AgentIdentity`; show its agent user. The ADO connection accepts no other caller (another agent gets `AADSTS501051`). Open the wiki history of `/Workshop/Approval-Sandbox`: John's Teams Approve commit is authored by **documentation-agent (agent user)** ([guide](agent-identity-guide.md), [identity table](resource-organization-guide.md#identities-who-authenticates-where)) | Use the slide's table. Wiki history is a read; no new write. Name the security debt below |
| 11:06-11:10 | 4 | **Agent 365** (slide 5): registry, access, security, lifecycle ([source](slides/agent-365.md), [#46](https://github.com/wdhm/foundry-agentic-pattern/issues/46)). Hand over to Louise | Slide only |

Total: **2 + 13 + 13 + 8 + 4 = 40 minutes**. Keep questions for the shared 11:50 Q&A. If a view fails, switch to its fallback at once; do not debug access on stage.

**Backup slides, only if asked:** [Work IQ](slides/work-iq.md) ([#47](https://github.com/wdhm/foundry-agentic-pattern/issues/47)) and [PDF/SharePoint sources](slides/document-sources.md) ([#48](https://github.com/wdhm/foundry-agentic-pattern/issues/48)).

## Set up the showcase

Do this the day before and again 30 minutes before the slot. Every step is read-only.

1. **Sign in** to the Foundry portal as the tenant admin.
2. **Playground:** in `documentation-agent`, ask the three questions above once. Pass: the Foundry IQ answer cites DS-14; the comparison answer links the repo at `97990d1`, the wiki page and work item 1; the update request is refused. Screenshot each answer and its trace as a backup.
3. **Proof views:** Agents → Traces shows both traces with the spans named above; Knowledge → Knowledge bases lists `kb-doc-agent` (via project connection `srch-foundry-agentic-r8n3ld`, Entra ID); the gateway Log stream shows `authorized caller oid=ea9e8fb5-…`; VS Code Foundry Toolkit lists both toolboxes.
4. **Browser tabs**, in demo order:
   - [Foundry portal](https://ai.azure.com) → project `proj-agentic` → Agents → `documentation-agent` → Playground (new chat), then Agents → Traces, then Knowledge.
   - VS Code → Foundry Toolkit → `proj-agentic` → Toolboxes.
   - [Azure portal](https://portal.azure.com) → Container App `ca-doc-agent-mcp` → Monitoring → Log stream.
   - [Microsoft Entra admin center](https://entra.microsoft.com) → Agent ID → `foundry-agentic-R8N3LD-proj-agentic-documentation-agent-AgentIdentity` (`ea9e8fb5-…`), and Users → `documentation-agent@…` (the agent user).
   - [Wiki page `/Workshop/Approval-Sandbox`](https://dev.azure.com/foundry-agentic/integration-team/_wiki/wikis/integration-team.wiki?pagePath=/Workshop/Approval-Sandbox) → History. Commits `d3ddedec71` (Teams Approve, 2026-10-20) and `ca622ad0cf` are by the agent user.
   - [Wiki page `/Order Sync/Overview`](https://dev.azure.com/foundry-agentic/integration-team/_wiki/wikis/integration-team.wiki?pagePath=/Order%20Sync/Overview) (fallback).
5. **Open the deck** in presenter view; the notes hold the talk track.

## Chat on the hosted agent

Chat is read-only: "approve it" in chat stays conversation, and real decisions use the Teams card. Citations in chat are model-generated, not the assessment contract's verified evidence ([agent README](../../src/agents/documentation-agent/README.md)). The chat reply does not list tool calls; Agents → Traces does. Every chat turn is traced through the project's Application Insights `appi-foundry-agentic`, so the trace is the evidence that Foundry IQ and the toolbox were used. Traces can take a minute or two to appear; if the new one is missing, open the rehearsal trace. GitHub PR #62 is outside the chat source scope.

**Fallback:** prompt agent `p2-demo-agent` (toolbox `p2-demo-toolbox:1`: Foundry IQ + read-only GitHub, no ADO) answers the Foundry IQ question and shows its tool calls in the playground.

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

- **Before rehearsal:** ask both playground questions once and screenshot the tool calls, open all tabs (Foundry playground, knowledge base, toolboxes, ADO wiki + history, Entra Agent ID), and verify presenter access to each.
- **Teams:** the Teams card is John's demo. The app is now installed for everyone in the tenant (2026-10-21); propagation can take up to 24 hours. A second-user Teams test is tracked on [#31](https://github.com/wdhm/foundry-agentic-pattern/issues/31).
- **Shared deck:** John copies the slide sources into the deck ([#39](https://github.com/wdhm/foundry-agentic-pattern/issues/39)); all three rehearse ([#40](https://github.com/wdhm/foundry-agentic-pattern/issues/40)).
