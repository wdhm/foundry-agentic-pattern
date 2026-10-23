# Manual setup runbook

> **Why manual?** [ADR 0020](adr/0020-manual-setup-first.md): the shared environment is set up manually. This runbook is the **single source of truth** for recorded environment changes. Full `azd` + Bicep provisioning is deferred/optional under accepted ADR 0022 ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)), not a workshop prerequisite.
>
> **Owner:** P3: Louise ([@llandinl](https://github.com/llandinl)), [#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5). **Rule:** if you change anything in Azure, update this file in the same PR.

## Shared workshop environment

This is **the** environment for development and the workshop. Don't create parallel resource groups or Foundry resources; add to these. How the resource, project, connections and identities fit together: [resource organisation guide](workshop/resource-organization-guide.md).

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

**P3 platform-first MVP approved 2026-10-16:** this package covers the existing
Foundry project, model versions/quota and native server-side tracing
([#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5),
[#49](https://github.com/wdhm/foundry-agentic-pattern/issues/49), native subset of
[#9](https://github.com/wdhm/foundry-agentic-pattern/issues/9)).
The P3 approval supersedes the older "proposed" wording in ADR 0022.
Cosmos DB and its RBAC, custom OpenTelemetry exporters/dimensions, custom
workbooks, APIM and new azd/Bicep provisioning are **not MVP prerequisites**.
Historical deployment instructions below are retained as dated evidence, not
instructions to redeploy over the current serving pin.

### Promotion, timed rollback and cleanup (P2, 2026-10-20)

Version 7 is now the serving version. The table below records the promotion, a
timed rollback drill and the removal of unused resources. Response IDs and raw
outputs are kept in the operator's evidence folder; nothing secret is recorded.

| Step | Evidence |
|---|---|
| Promote 6 → 7 | Selector PATCH + readback in 5.6 s; rest of `agent_endpoint` unchanged. Named-path outer `agent_reference.version` is now `7`, so the 2026-10-19 version caveat no longer applies |
| `order-sync-information-missing` on serving v7 | `insufficient_information`, recall 3/3, checker pass (`caresp_08d13f17…`) |
| `order-sync-retry` on serving v7, 5 runs | Recall 3/3 in every completed run, but status `gaps_found` only 2/5: 2 runs returned `insufficient_information`, 1 failed closed on evidence verification. Status stability is a P1 follow-up on [#13](https://github.com/wdhm/foundry-agentic-pattern/issues/13) |
| Timed rollback 7 → 6 ([#34](https://github.com/wdhm/foundry-agentic-pattern/issues/34)) | **89.7 s** from PATCH to a completed fresh named-path response with outer version `6` (`caresp_01afca10876bc29f001j01WVPAgpJ2dsi0jpe4zHyXi0KGjzNd`); trace `operation_Id` `c03be3c46a2b725b5230e590e8dfe7d8`, `gen_ai.agent.version=6`, 7 `chat` spans, 53,045 input / 7,680 output tokens summed over those spans |
| Roll forward 6 → 7 | **72.5 s**, outer version `7`, checker pass (`caresp_0e98f4dab11d436f00JtYmy5jqMwYmxezUI57d4S4b3ICpKS8H`); trace `9c4a0846884a17f5bf782382ccc2f0de`, `gen_ai.agent.version=7`, 5 `chat` spans, 46,754 / 5,250 tokens |
| Rollback caveat | Version 6 rejects the v7 request field `task` (`extra_forbidden`). A rollback across a contract change needs callers that send the older request shape; the drill sent a v6-shaped request. v6 quality on the information-missing scenario was not a pass (it predates `task.scope`) |
| Cleanup | Deleted `documentation-agent` versions 1–2, the prompt agent `doc-agent` (agent user, ADO entitlement, delegated grant, gateway app-role; its agent identity and blueprint were removed with it), the unused Cosmos DB account, and unreferenced ACR tags/manifests. Remaining images: v6 `1a00ba37`, v7 `a12275d5`, approval v8 `2093e80b`, gateway `ado-mcp:0.2.1` |

Current state: serving `documentation-agent:7` at 100%; v6 retained as the
rollback target; v8 is the approval-mode version used through version-specific
sessions. Code paths that target the prompt agent (`--target prompt`, the
`doc-agent` onboarding examples) now need the agent re-created before use.
Cosmos-backed approval state is an optional later milestone (see
[next steps](next-steps.md)).

### Recorded hosted serving and candidate state (2026-10-19)

This summarizes the last recorded reads and P1 handoff, not a fresh inventory on
2026-10-20. Refresh the exact target before any new approved cloud operation.

| Surface | Recorded state / evidence |
|---|---|
| Named serving | Concrete `documentation-agent:6` at 100%; P1 pinned it before creating candidate 7 and recorded a fresh named-path version-6 baseline |
| Serving artifact | Digest `sha256:1a00ba37c7923b171fc13b36f16dde2592aead1e02cd5fc4fdd9ef7f75c5f863`, application provenance `0.3.0`, source `2b77527` |
| Candidate | `documentation-agent:7`, active but **not promoted**, digest `sha256:a12275d5a2176b722e6a65de23355d44ed7a327edf024f00451ac7872649dcf0`, source `89e8593`, assessment provenance `0.4.0` |
| Candidate acceptance | P1 reports both original task-aware scenarios passing the unchanged checker, 3/3 expected items each; this is not the full five-case built-in evaluator gate |
| Candidate version caveat | Session GET binds version 7, but outer Responses reports version 6. Preserve both observations; the CLI fails explicitly on disagreement instead of claiming candidate success |
| Tool access | Own hosted identity/user, read-only gateway revision 5, toolbox `documentation-agent-readonly:1`; prompt `doc-agent` ADO access is interrupted by the coordinated cutover |
| Independent P3 proof | One concrete-version-6 assessment completed with contract/source-version/reviewed-source provenance checks; see the [dated smoke](#hosted-packaging-and-independent-smoke-p3-2026-10-19) |
| Subsequent telemetry proof | Read-only lookup on 2026-10-20 correlated the same v6 run with native model/tool spans, observed model revision and layer-specific usage; see [evidence below](#hosted-native-trace-evidence-2026-10-20) |
| Still unverified | Full hosted evaluation/tool-call accuracy, live approved wiki writes, Teams delivery and timed rollback |

P1's [acceptance handoff](https://github.com/wdhm/foundry-agentic-pattern/issues/13#issuecomment-6270385634)
records candidate 7 and the serving pin. The
[deployment guide](workshop/hosted-deployment-guide.md#version-selection-and-later-p1-handoff)
separates that handoff from P3's own version-6 smoke.

- [x] Resource group `rg-foundry-agentic-pattern` in Sweden Central
- [x] **Foundry resource** `foundry-agentic-R8N3LD` + **Foundry project** `proj-agentic`
- [x] **Model deployments**: one **chat** model (agent) and one **eval** model (evaluators). On 2026-10-20 the chat deployment `gpt-6-luna` was pinned to `NoAutoUpgrade`, and the evaluator deployment `eval-gpt-5.4-mini` (`gpt-5.4-mini` `2026-03-17`, `GlobalStandard` 50K TPM, `NoAutoUpgrade`) was created. See the dated inventory below.
- [x] **Log Analytics** + **Application Insights**, connected to the Foundry project; native prompt-agent trace ingestion verified 2026-10-16 (evidence below)
- Deferred: **Cosmos DB** and containers ([ADR 0016](adr/0016-state-and-audit-cosmos-db.md)); target architecture, not the approved MVP
- [x] Team access: tenant accounts for John, Rickard and Louise are Owner on the subscription (see the team accounts table)
- [x] All three tenant accounts are users (Basic) in the Azure DevOps org `foundry-agentic`
- Deferred: project managed identity to Cosmos DB data contributor
- [x] **Azure DevOps** org `foundry-agentic`, project `integration-team`, project wiki (connected to the tenant)
- [x] A few fictional work items + wiki pages ([ADR 0005](adr/0005-generic-repo-with-fictional-data.md)); replaced by mock data in [#17](https://github.com/wdhm/foundry-agentic-pattern/issues/17). Needed by the P2 spike [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2).

### P3 read-only inventory (2026-10-16, 07:57 UTC; before monitoring approval)

Read from the shared environment using the **WSL Ubuntu Azure CLI**; no cloud
resources, model settings, connections, agent definitions, identities or traffic
were changed during this inventory. These are historical point-in-time
observations. The subsequently approved monitoring setup and ingestion evidence
are recorded in the native tracing section below.

| Item | Observed value |
|---|---|
| Foundry resource | `foundry-agentic-R8N3LD`, `AIServices`, Sweden Central, provisioning `Succeeded` |
| Prompt agent | `doc-agent:3`, model deployment `gpt-6-luna` (data-plane GET, API `2025-11-15-preview`) |
| Hosted stub | Separate P1 `documentation-agent`; not invoked or changed by this package |
| Project connections | `ado-mcp-proxy` (`RemoteTool`, `AgenticIdentityToken`), `kb-doc-agent-mcp` (`RemoteTool`, `ProjectManagedIdentity`), `github-mcp` (`RemoteTool`, `CustomKeys`) |
| Native tracing connection | No Application Insights connection in the project connection list |
| Monitoring resources in shared RG | No Application Insights components or Log Analytics workspaces |
| Other subscription monitoring resources | Exist outside the shared RG; ownership/suitability not established, so not reused |
| Model invocation / trace ingestion / three-owner access | Not verified at inventory time; subsequent single-owner native tracing proof below, three-owner checks still open |

| Deployment | Model version | Type / capacity units | Upgrade policy | Reported rate limits | State |
|---|---|---|---|---|---|
| `gpt-6-luna` | `2026-09-22` | `GlobalStandard` / `500` | `OnceNewDefaultVersionAvailable` | `500000` tokens / `60s`; `500` requests / `60s` | `Succeeded` |
| `text-embedding-3-large` | `1` | `Standard` / `120` | `OnceNewDefaultVersionAvailable` | `120000` tokens / `60s`; `120` requests / `10s` | `Succeeded` |
| Separate eval deployment | **Absent** | Not allocated | Not configured | Not measured | Pending approval |

The embedding deployment serves Foundry IQ; it is **not** an evaluator chat
model. Preserve it. A version value alone does not mean a deployment is pinned.

**Update 2026-10-20 (P2, approved in the team session):**

| Deployment | Model version | Type / capacity | Upgrade policy | Evidence |
|---|---|---|---|---|
| `gpt-6-luna` | `2026-09-22` | `GlobalStandard` / `500` (unchanged) | **`NoAutoUpgrade`** | ARM PUT `Succeeded` |
| `eval-gpt-5.4-mini` | `2026-03-17` | `GlobalStandard` / `50` (50K TPM) | **`NoAutoUpgrade`** | ARM PUT `Succeeded`; a one-prompt smoke test returned model `gpt-5.4-mini-2026-03-17` |

Use `EVAL_MODEL_DEPLOYMENT=eval-gpt-5.4-mini` for the evaluation gate. Cost is
pay-per-token only; there is no reserved capacity.

Regional subscription quota returned by `az cognitiveservices usage list`:

| Quota name (Sweden Central) | Current | Limit | API unit |
|---|---|---|---|
| `OpenAI.GlobalStandard.gpt-6-luna` | `500` | `250` | `Count` |
| `OpenAI.Standard.text-embedding-3-large` | `120` | `350` | `Count` |

**Quota anomaly:** chat allocation exceeds the reported limit. Do not treat this
as negative usable capacity, infer available eval capacity, or resize the
working chat deployment to "fix" it. Confirm **Management center > Quota** and
the selected model/type/region with the subscription owner before proposing an
eval allocation. Quota is shared at subscription/region/model/deployment-type
level, not per project. Capacity units are model-specific; the rate-limit
values above came from deployment metadata, not a universal TPM conversion.
Limits do not guarantee throughput under load.

#### Repeat the inventory without cloud changes

Run from the repo root in PowerShell (5.1 or newer):

```powershell
# Use whichever CLI already has a valid tenant login; no login is triggered.
.\infra\scripts\get-foundry-platform-state.ps1
# Windows and WSL have separate CLI token caches:
.\infra\scripts\get-foundry-platform-state.ps1 -UseWsl
```

For a Windows checkout reached via a WSL UNC path, the unsigned-script policy
can block execution. Where local policy permits, the process-only invocation
used for this inventory is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\scripts\get-foundry-platform-state.ps1 -UseWsl
```

This does not change the machine's execution policy. Follow managed signing
policy instead if required.

The [script](../infra/scripts/get-foundry-platform-state.ps1) explicitly scopes
each read to the selected subscription. It emits timestamped JSON containing
deployment versions, upgrade policies, rate limits, matching regional quotas,
monitoring resource names and connection categories/auth types. It never lists
keys, connection credentials or connection strings, never invokes an agent,
and stops on the first failed read rather than returning a success-shaped empty
inventory. `traceIngestionVerified=false` is deliberate: configuration inventory
cannot prove ingestion.

On 2026-10-16, Windows `az account show` returned cached subscription metadata
but subsequent ARM reads failed with "User ... does not exist in MSAL token
cache." The existing WSL CLI login worked. **`account show` alone is not an
authentication check.** If both CLIs fail, a human must sign in using the tenant
account and commands at the top of this runbook; do not copy token caches,
credentials or access tokens between environments.

Offline script checks (no Azure login, network calls or extra test packages):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\scripts\tests\get-foundry-platform-state.Tests.ps1
```

### Model deployment choices and version changes (#49)

Keep the working chat deployment and shared agent untouched. `GlobalStandard`
is the observed chat deployment type; it is **not** evidence that inference
stays in Sweden Central. If data residency matters, review the
[deployment types](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/deployment-types)
before approving an eval model/type. This MVP does not add an AI Gateway or
repoint any existing gateway.

For reproducibility the proposed policy is an explicit model version with
`NoAutoUpgrade`, followed by a deliberate, evaluated version change. This policy
is **not yet applied** to the chat deployment. Pinning does not prevent model
retirement; review lifecycle notices and arrange upgrades before retirement.
See [model versions and upgrades](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/model-versions)
and [quota management](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/quota).

Repeatable manual procedure, **only after approval of the exact changes**:

1. Refresh the inventory. In Foundry **Models + endpoints**, inspect
   `gpt-6-luna`: version `2026-09-22`, type `GlobalStandard`, capacity `500`.
   Capture current settings before editing.
2. Propose changing **only** its version upgrade policy to `NoAutoUpgrade`,
   preserving version, capacity, model name and deployment name. Request
   approval before saving. If the portal cannot preserve those fields, stop.
3. For the evaluator, select a built-in-evaluator-supported chat model from the
   current catalog. Record the **exact model/version, proposed deployment name,
   deployment type, region, capacity, upgrade policy and estimated cost**.
   Resolve the quota anomaly first. Request approval before creating it on
   `foundry-agentic-R8N3LD`; do not create another Foundry resource.
4. After approval, create that deployment in the existing resource, explicitly
   selecting its version and `NoAutoUpgrade`. Record the result and repeat the
   inventory. Do not silently reuse chat capacity or fall back to the embedding
   model. If a separate eval deployment is declined, leave
   `EVAL_MODEL_DEPLOYMENT` unset and record the user decision.
5. With separately approved model-call cost, have each owner invoke the chat
   model with a small fictional prompt; record UTC time, deployment/version,
   success or error (never credentials). Verify the eval deployment with its
   intended evaluator. Provisioning `Succeeded` is not invocation evidence.
6. For a later upgrade, review model retirement, propose the exact new version,
   get approval, run the eval/release gate and record its outcome. Agent version
   rollback alone does **not** restore a changed model deployment version.

No eval model/version/capacity is preselected here: current catalog support,
quota and deployment cost have not been established. #49's two pinned
deployments acceptance criterion remains open.

### Native tracing setup and demonstration (#5, native subset of #9)

Use [Foundry server-side tracing](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup):
connecting Application Insights enables platform traces without custom
OpenTelemetry code. No custom workbook, Cosmos join or application-defined
`run_id`/version dimensions are promised by this MVP.

**Approved and executed 2026-10-16:** the user approved creating workspace
`log-foundry-agentic` and workspace-based Application Insights
`appi-foundry-agentic` in the existing resource group, Sweden Central, with
30-day retention and the project connection/required monitoring role assignment,
acknowledging ingestion charges. No approval was given for chat pinning, eval
deployment or agent/routing changes. The setup used **Project managed identity**
and **Monitoring Metrics Publisher** scoped to the Application Insights
component, not the resource group or subscription.

Repeatable manual procedure (requires the same explicit approval):

1. Azure portal > the existing resource group > **Create > Log Analytics
   workspace**: use the approved name/region. Set the approved retention.
   Create **Application Insights**, selecting that workspace. Record actual
   resource names, regions, retention and the workspace association; if Sweden
   Central is unavailable, stop for a region decision instead of choosing one
   silently. Existing AI Search (France Central) and Container Apps (North
   Europe) exceptions are unrelated and remain unchanged.
2. Foundry (new) > `proj-agentic` > **Agents > Traces > Connect** > choose the
   existing `appi-foundry-agentic` > **Connect**. Alternative:
   **Manage > Project details > Connected resources > Add connection >
   Application Insights**. Select **Project managed identity** where supported;
   follow [Entra trace ingestion](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-ingestion-entra-authentication).
   If unavailable, stop and review the supported authentication method rather
   than enabling key auth without approval.
3. Inspect the resulting connection and identity role assignment. Ensure
   viewers have **Log Analytics Reader** access to the connected telemetry;
   protected tables can additionally require **Privileged Monitoring Data
   Reader**. Do not assume subscription resource access proves log-query access.
4. Refresh the inventory. A connection/resource appearing proves configuration
   only, not ingestion.
5. With approval for model-call and telemetry costs, invoke the current
   **prompt agent `doc-agent`** once with a fictional, no-write scenario.
   Keep native tool approval; decline any proposed write. Do not invoke the
   hosted `documentation-agent` stub as proof of model-backed prompt-agent
   tracing, change instructions, repoint gateways or recreate retired agents.
6. Record UTC timestamp, exact agent version, model deployment/version,
   Response ID, Conversation ID and Trace ID. Wait a few minutes for ingestion.
   In **Agents > Traces**, find the response/trace, open its spans and verify
   duration/status and model/tool operations. Save a redacted screenshot or
   trace link. Never commit raw prompt/tool content, tokens or connection strings.

For a minimal correlation check, open **Application Insights > Logs**
(application scope) and substitute the Trace ID shown by Foundry for
`<trace-id>`; `operation_Id` is Application Insights' trace correlation field:

```kusto
let traceId = "<trace-id>";
union withsource=Table requests, dependencies, traces, exceptions
| where timestamp > ago(24h)
| where operation_Id == traceId
| project timestamp, Table, operation_Id, operation_ParentId
| order by timestamp asc
```

This intentionally omits message bodies/custom dimensions. At workspace scope,
use `AppRequests`, `AppDependencies`, `AppTraces`, `AppExceptions` with
`TimeGenerated`, `OperationId`, `ParentId` instead. An empty result is **not**
success: check time range, correct app/workspace, ingestion delay, connection
auth/RBAC and whether the invocation generated platform traces. Stop and record
the error if the connection or ingestion cannot be verified.

#### Executed setup and trace evidence (2026-10-16)

| Setting | Verified observation |
|---|---|
| Log Analytics | `log-foundry-agentic`, Sweden Central, `PerGB2018`, provisioning `Succeeded`, workspace retention `30` days |
| Application Insights | `appi-foundry-agentic`, Sweden Central, workspace association to `log-foundry-agentic`, provisioning `Succeeded` |
| Ingestion auth | `DisableLocalAuth=true`; no key-based ingestion |
| Project connection | `appi-foundry-agentic`, category `AppInsights`, auth `ProjectManagedIdentity`, target the component ARM resource ID, shared within the project |
| Connection metadata | `ApiType=Azure`, `ResourceId` points to the component, required `ApplicationInsightsConnectionString` routing metadata passed internally; its value is not printed or committed |
| Ingestion RBAC | `proj-agentic` **system-assigned project managed identity**, principal type `ServicePrincipal`, **Monitoring Metrics Publisher** on the component only |
| Table retention | All 12 Application Insights tables, including `AppDependencies`, `AppRequests`, `AppTraces` and `AppGenAIContent`: analytics and total retention explicitly `30` days |
| Existing connections | `ado-mcp-proxy`, `kb-doc-agent-mcp`, `github-mcp` preserved; no model, agent definition, identity or gateway edits |

The [setup script](../infra/scripts/setup-native-tracing.ps1) targets only these
approved shared resources. It previews by default, requires `-Apply` to mutate,
reuses matching resources, and stops on conflicting configuration rather than
overwriting it. It waits for resource provisioning and verifies the scoped role
and connection. It does not invoke the agent or grant log-reading/content roles.

```powershell
# Preview; no cloud writes:
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\scripts\setup-native-tracing.ps1 -UseWsl
# Only with explicit approval for the documented monitoring changes:
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\scripts\setup-native-tracing.ps1 -UseWsl -Apply
# Offline guard/idempotency tests:
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\scripts\tests\setup-native-tracing.Tests.ps1
```

API versions used: Log Analytics workspace `2023-09-01`, Application Insights
`2020-02-02`, tables `2022-10-01`, Foundry project connection
`2025-10-01-preview`. Microsoft Learn's generated connection schema lags the
runtime `ProjectManagedIdentity` auth value; the live API accepted and returned
it. The first connection PUT failed explicitly because the API also requires
`metadata.ApplicationInsightsConnectionString`. This is routing metadata, not a
credential granting ingestion with local auth disabled; it is passed through a
temporary request file deleted in `finally`, never emitted in the result.
No keys or connection credentials were retrieved.

**Retention gotcha:** a 30-day workspace setting did not change the platform's
90-day defaults on Application Insights tables. The script sets both analytics
and total retention to 30 on those tables and verifies them. These are configured
retention periods, not a guarantee of deletion at exactly 30 days; Azure's
[retention semantics](https://learn.microsoft.com/azure/azure-monitor/logs/data-retention-configure)
still apply. No immediate-purge policy or custom ingestion cap was added.

**Ingestion is verified, not just configured.** One approved read-only assessment
used the current prompt agent `doc-agent:3`, existing deployment `gpt-6-luna`
version `2026-09-22`, the fictional contract request and `tool_choice="none"`.
It used the project Responses API with an explicit agent reference, **not**
the named serving endpoint and not the hosted stub. There were three MCP tool
discovery items, reasoning and a completed message, but no tool calls, approvals
or external writes. Model usage was 6,071 input / 367 output tokens.

| Correlation field | Observed value |
|---|---|
| Invocation UTC | Started `2026-10-16T08:26:36Z`, completed `08:26:44Z` |
| Response ID | `resp_0549388dc8b13e63006ad1dfbbb3b481908917858a50e93a62` |
| Conversation ID | `conv_0549388dc8b13e6300q1zF0viuUKWFvTlxHxKSg1pOAyRoQ6f5` |
| Trace ID / `operation_Id` | `7e43610cdbc2a300abe6a5cd94501285` |
| Agent span | `invoke_agent doc-agent:3`, span `3f220bc487b413d6`, duration `4294.7717` ms, success `True` |
| Child model span | `chat gpt-6-luna-2026-09-22`, span `6f90e394deb3be50`, parent `3f220bc487b413d6`, duration `1871.4673` ms, success `True` |
| Native attributes on both spans | `gen_ai.agent.name=doc-agent`, `gen_ai.agent.id=doc-agent:3`, request/response model `gpt-6-luna-2026-09-22`, exact response/conversation IDs above |

The first lookup returned no rows during ingestion delay; a later query
returned the two successful `dependencies` spans with the same Trace ID.
Telemetry read access was demonstrated for the executing team account, not all
three owners. No raw prompt, response text, tool content or connection-string
value is stored here.

To reproduce the evidence lookup in **Application Insights > Logs**, use:

```kusto
dependencies
| where timestamp > ago(24h)
| where customDimensions["gen_ai.response.id"] ==
    "resp_0549388dc8b13e63006ad1dfbbb3b481908917858a50e93a62"
| project timestamp, name, duration, success, operation_Id, id, operation_ParentId,
    agent=tostring(customDimensions["gen_ai.agent.id"]),
    model=tostring(customDimensions["gen_ai.response.model"])
| order by timestamp asc
```

For later reproductions, select the recorded UTC interval instead of `ago(24h)`;
the telemetry will eventually expire under the configured retention.
In Foundry, open `proj-agentic > Agents > Traces` and search the response or Trace
ID above. Ingestion and correlation were checked via the Application Insights
query API; the Foundry portal UI itself was not visually verified.

This historical no-tools assessment does not itself prove tool-operation
tracing, all-owner access, hosted tracing or release routing. The later hosted
evidence below supplies model/tool tracing, not those other acceptance items.
Custom dimensions/Cosmos joins remain deferred under ADR 0022.

#### Hosted native trace evidence (2026-10-20)

A bounded read-only query of existing `appi-foundry-agentic` telemetry found
the native spans for the **same single approved October 19 version-6
assessment**. No new invocation, exporter, instrumentation, deployment, resource
write, login retry or shared-default change was needed.

| Correlation field | Observed value |
|---|---|
| Root request UTC | `2026-10-19T20:26:48.6357167Z` |
| Root request | `invoke_agent`, success `True`, result code `0`, duration `44405.3458` ms |
| Response ID | `caresp_07f56b96a4570142006ZLICnpGolpBim8MaVNlt2LHeVEAxsAT` |
| Session ID | `085a49a276d25fb800zlWraicaL3nXr3Rtpsa1JICOquJV5SV2` |
| Trace ID / `operation_Id` | `d35d1af1350e3f97df6dd149d69f01ab` |
| Root span / parent | `0f5fb945b61561b7` / `fa8a8aad35f53858` |
| Agent | `documentation-agent`, explicit `gen_ai.agent.version=6`; `gen_ai.agent.id` is an identity GUID, not the version |
| Complete bounded aggregate | 1 request, 25 dependencies, 85 traces; no custom events, exceptions or failed request/dependency spans in the queried operation |
| Application model layer | Three `chat gpt-6-luna` spans, observed response model `gpt-6-luna-2026-09-22`; 19,002 input / 2,715 output tokens summed only at this layer |

Native `tools/list` succeeded in 2.218 seconds. Five application `execute_tool`
spans succeeded, each with a same-operation child `tools/call` and matching name:

| Tool | Calls | Observed application duration (seconds) |
|---|---|---|
| `knowledge___knowledge_base_retrieve` | 1 | 1.016 |
| `github___get_file_contents` | 2 | 1.655 / 1.735 |
| `ado___wiki` | 1 | 3.431 |
| `ado___wit_work_item` | 1 | 1.238 |

Nested platform model spans and a `multi_tool_use.parallel` wrapper also exist.
Do not double-count model usage across application/platform layers or count the
wrapper as an additional backend tool call. These successful spans prove
observed execution, **not** correct arguments, schemas, outputs or a passing
`tool_call_accuracy` evaluation.

For a content-free application-scope lookup while the telemetry is retained:

```kusto
let traceId = "d35d1af1350e3f97df6dd149d69f01ab";
union withsource=Table requests, dependencies, traces, exceptions
| where timestamp between (datetime(2026-10-19T20:25:30Z) .. datetime(2026-10-19T20:29:00Z))
| where operation_Id == traceId
| project timestamp, Table, operation_Id, operation_ParentId
| order by timestamp asc
```

The root response/session/version attributes and `operation_Id` provide the
verified native join. Caller request/correlation IDs were found only inside
`gen_ai.input.messages` on nine dependencies, not as dedicated structured
correlation attributes. The server-side check selected attribute keys and
presence/counts only, not message content. Native telemetry includes attribute
keys for instructions, messages and tool content; do not export their values
or assume the telemetry is content-free. Dedicated non-content caller-ID
attributes require a separate scoped decision, not a speculative exporter.

Sanitized queries/results are retained in the deployment owner's ignored
`.azure/hosted-smoke-telemetry-*.json`. The complete aggregate, not the first
100-row sample, establishes the 111-row count. This supersedes the earlier
outer-response-only model/usage/trace visibility limit for this run. It does
not prove candidate-7 execution, all-presenter access, portal UI presentation,
evaluation correctness or any wiki write.

### Handoff to eval/release work

Do not mark the cloud setup complete until these outputs are supplied:

| Output | Current value / required evidence |
|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | Existing endpoint in Outputs below |
| Agent selector | Hosted `documentation-agent`; last recorded serving `6`, candidate `7`. Choose a reviewed concrete target with verified execution evidence; do not follow latest or substitute prompt-agent evidence |
| `CHAT_MODEL_DEPLOYMENT` / model version | `gpt-6-luna` / `2026-09-22`; currently auto-upgrades, so record the observed version per eval run |
| `EVAL_MODEL_DEPLOYMENT` / model version | `eval-gpt-5.4-mini` / `2026-03-17` (deployed 2026-10-20). Thresholds still need calibration (#25) |
| Capacity evidence | Fresh regional quota + deployment rate limits; resolve chat `current=500`, `limit=250` discrepancy |
| Tracing destination | `appi-foundry-agentic` / workspace `log-foundry-agentic`; project `AppInsights` / `ProjectManagedIdentity` connection and project-MI ingestion role verified |
| Native trace proof | Prompt-agent spans and correlated hosted-v6 model/tool spans above; hosted model revision and layer-specific usage observed in telemetry. Portal UI not visually verified; candidate-7 proof and evaluation correctness remain separate |
| Access proof | Each owner's chat invocation and telemetry read result; not verified here |

Eval/release automation must fail explicitly if its evaluator deployment is
unset; it must not provision resources, mutate the shared agent or substitute a
model as a hidden fallback. No tracing connection string is needed by the caller
for server-side tracing. CI identity/workflow, evaluation cases and release
mechanics belong to the subsequent work package.

## Phase 2: Added by the tracks (M1–M3)

| Resource | When / issue | Owner |
|---|---|---|
| **Azure AI Search** + Foundry IQ knowledge base | [#19](https://github.com/wdhm/foundry-agentic-pattern/issues/19) | P2 ✅ `srch-foundry-agentic-r8n3ld` in **France Central** (Sweden Central had no capacity). Run [`setup-foundry-iq.ps1`](../infra/scripts/setup-foundry-iq.ps1); see the [guide](workshop/foundry-iq-guide.md) |
| **GitHub MCP** connection `github-mcp` (read-only, fine-grained token) | [#20](https://github.com/wdhm/foundry-agentic-pattern/issues/20) | P2 ✅ Run [`setup-github-mcp.ps1`](../infra/scripts/setup-github-mcp.ps1); see the [guide](workshop/github-mcp-guide.md). The token expires after 90 days; re-run the script with a new one |
| **Agent identity** role assignments (DevOps, Search) | [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2), [#28](https://github.com/wdhm/foundry-agentic-pattern/issues/28) | P2 (Azure DevOps ✅, see below). GitHub doesn't accept Entra tokens, so it uses the token above |
| **AI Gateway (APIM)**: model/read-toolbox/assessment Responses routes | [Optional integration and approval prerequisites](ai-gateway.md); historical #3/#23 slide disposition | P3; opt-in repository configuration only, not deployed or live enforcement |
| Hosted agent deployment | [#7](https://github.com/wdhm/foundry-agentic-pattern/issues/7) | P1 |
| Teams / M365 publish | [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4) | P3 |

Document each step here when you do it: portal path or CLI command, settings chosen, and any gotchas.

### Hosted contract stub (P1, #7)

**Historical version-2 deployment record.** The current primary path is the
version-6 assessment with unpromoted candidate 7 described above. These original
stub deployment commands must not be rerun over that state without a new plan.

`documentation-agent` version **2** is the
Agent Framework contract stub, separately from the prompt agent `doc-agent`: no model calls,
tools, wiki writes or Cosmos persistence. Application provenance version `0.1.0`
is distinct from Foundry deployment version `2`.

The tested Linux x64 image is in the existing registry
`acrfoundryagenticr8n3ld`, repository `documentation-agent`, tag `stub-0.1.0`.
Deployment pins digest
`sha256:0ea1b08788643623e49ee75ab7e7013e3103ed8d551072461e8102eb39cc0220`.
No new registry, project, resource group or model deployment was provisioned.

Build and local HTTP instructions are in the
[agent README](../src/agents/documentation-agent/README.md). The deployment used
an isolated local azd workspace, not repo-wide infrastructure provisioning:

```powershell
az acr login --name <existing-registry>
docker tag documentation-agent:0.1.0 <registry-host>/documentation-agent:stub-0.1.0
docker push <registry-host>/documentation-agent:stub-0.1.0

# In a separate, non-git-ignored deployment workspace:
azd ai agent init --no-prompt --agent-name documentation-agent `
  --project-id <existing-project-arm-id> `
  --image <registry-host>/documentation-agent@sha256:<image-digest> `
  --protocol responses
# Change directory into the generated documentation-agent folder.
azd env set AZURE_CONTAINER_REGISTRY_ENDPOINT <registry-host>
azd env set AZURE_CONTAINER_REGISTRY_RESOURCE_ID <existing-registry-arm-id>
azd env set AZURE_CONTAINER_REGISTRY_NAME <existing-registry>
# In generated azure.yaml: docker.imagePassthrough=true, docker.remoteBuild=false.
azd deploy documentation-agent --no-prompt
azd ai agent show --output json

$request = Get-Content <path-to-example-request.json> -Raw |
  ConvertFrom-Json | ConvertTo-Json -Depth 10 -Compress
azd ai agent invoke documentation-agent $request --protocol responses `
  --new-session --new-conversation
azd ai agent invoke documentation-agent '{}' --protocol responses `
  --new-session --new-conversation
```

Valid remote input returned a schema-valid `AgentResult` with the original
request ID; `{}` failed explicitly with missing-field errors. Foundry evaluation
suite generation was deferred because this stub does not perform model reasoning.

| Gotcha | Resolution |
|---|---|
| Docker Desktop WSL engine crashed during the first build | Restarted after WSL setup; built explicitly for `linux/amd64` on the ARM64 development machine |
| Container pip TLS handshake to the public package host failed | Used the developer machine's configured HTTPS package mirror as a credential-free build argument; no TLS bypass |
| azd initialization inside ignored `.azure/` failed staging template files | Initialized in a separate local deployment workspace outside the repository |
| `registryConnectionId` caused `not_a_registry_connection` | That option is for generic registries; removed it and used native ACR deployment settings. Removed the trial connection and project-level AcrPull grant |
| Multiline JSON positional input reached the agent as only `{` | Compressed JSON to one line before passing it to azd |

References: [existing ACR deployment](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-private-azure-container-registry),
[hosted agents](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry).

<a id="agent-identity-and-azure-devops"></a>
### Agent identity and Azure DevOps (P2, [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2))

The step-by-step guide with Microsoft Learn references is [docs/workshop/agent-identity-guide.md](workshop/agent-identity-guide.md); the decision is [ADR 0021](adr/0021-agent-user-and-ado-mcp-gateway.md). Look up IDs in Entra (portal or Graph); they're not stored here.

| Resource | Name / value | Notes |
|---|---|---|
| Chat model deployment | `gpt-6-luna` | In `foundry-agentic-R8N3LD` |
| Prompt agent | `doc-agent` (tools `knowledge`, `github`, `ado`) | Agent identity: `foundry-agentic-R8N3LD-proj-agentic-doc-agent-AgentIdentity` |
| Hosted agent | `documentation-agent` (assessment versions 6/7; approval candidate 8, never served) | Serving recorded in [Recorded hosted serving](#recorded-hosted-serving-and-candidate-state-2026-10-19); v8 added 2026-10-20 ([approval write path](#approval-write-path-p2-2026-10-20)). Agent identity: `foundry-agentic-R8N3LD-proj-agentic-documentation-agent-AgentIdentity`. **The gateway points at this agent** (read + write since 2026-10-20). Foundry User on the project, Monitoring Metrics Publisher on App Insights |
| Toolbox | `documentation-agent-readonly` (version 4, default) | Five read tools over `kb-doc-agent-mcp`, `github-mcp`, `ado-mcp-proxy`, including `ado___repo_file` ([`setup-toolbox.ps1`](../infra/scripts/setup-toolbox.ps1)) |
| Toolbox (write) | `documentation-agent-write` (version 1) | Only `ado___wiki_upsert_page` over `ado-mcp-proxy` (`setup-toolbox.ps1 -Write`). Used only by the approval runtime |
| Agent user (hosted) | `documentation-agent@M365CPI54615665.onmicrosoft.com` | Linked to the hosted agent identity. Azure DevOps **Basic** + `[integration-team]\Contributors` (Readers membership kept). Stakeholder + Readers until 2026-10-20 |
| Consent grant (hosted) | Hosted agent identity → **Azure DevOps MCP**, consentType `Principal` | Scopes `Ado.Mcp.Tools wit.read wiki.read wiki.write` (`wiki.write` added 2026-10-20) |
| Agent user | `doc-agent@M365CPI54615665.onmicrosoft.com` | Linked to the agent identity. Azure DevOps **Basic** + `[integration-team]\Contributors`. Kept for rollback |
| Consent grant | Agent identity → **Azure DevOps MCP** (`2a72489c-…`), consentType `Principal` (agent user) | Scopes `Ado.Mcp.Tools wit.read wiki.read wiki.write`. We created the Azure DevOps MCP service principal in the tenant. |
| User-assigned MI | `id-doc-agent-mcp` | Federated credential on both agents' **blueprints** (`mcp-server-uami` on `doc-agent`, `ado-mcp-gateway` on `documentation-agent`); AcrPull on the ACR |
| Gateway Entra app | `doc-agent-mcp-api` (`api://<appId>`) | App roles `Mcp.Tools.ReadWrite.All` (assigned to `doc-agent`) and `Mcp.Tools.Read.All` (assigned to `documentation-agent`) |
| Container registry | `acrfoundryagenticr8n3ld` (Basic, Sweden Central) | Image `ado-mcp:0.2.1` |
| Container Apps env | `cae-doc-agent-mcp` (**North Europe**) | Sweden Central had no capacity (`AKSCapacityHeavyUsage`); logs: console only |
| Container app (gateway) | `ca-doc-agent-mcp` | `https://ca-doc-agent-mcp.gentlemushroom-65b5f1ef.northeurope.azurecontainerapps.io/mcp` |
| Foundry connection | `ado-mcp-proxy` | `RemoteTool`, `AgenticIdentityToken`, audience `api://<gateway appId>` |

To onboard another agent, use the reviewed procedure in
[`onboard-agent.ps1`](../infra/scripts/onboard-agent.ps1)
([guide](workshop/agent-identity-guide.md#onboard-another-agent-automated)).
The gateway serves one agent at a time. It points at hosted `documentation-agent`
(`MCP_REQUIRED_ROLE=Mcp.Tools.Read.All`), so `doc-agent`'s `ado` tool returns `403`.
Since 2026-10-20 (revision `--0000006`) the gateway runs with
`ADO_MCP_READONLY=false`: it is **no longer read-only**. Which tools an agent can
call is limited by the toolbox allowlist, and writes go only through the approval
runtime (see [Approval write path](#approval-write-path-p2-2026-10-20)).
Repointing it to the prompt agent is a separate identity/gateway migration,
**not agent-version rollback**; do not rerun onboarding as a release step.

### Structured-output contract demo (P1, #12)

**Historical prompt-only contract demo:** `doc-agent` (version 1 in the
2026-10-14 inventory) replaced retired `doc-agent-spike`. This is not the current
hosted workshop target or proof of its source access. Since the coordinated
hosted cutover, the prompt agent's ADO tool returns `403`. Do not recreate the
retired spike. The version-4 result below is historical verification.

On 2026-10-13, `doc-agent-spike` **version 4** was created from version 3,
preserving the `gpt-6-luna` model, low reasoning effort and existing MCP tool
approval configuration. That version added native strict `AnalysisOutput`
JSON Schema and assessment-only instructions. Version 3 remained available at
that time; all spike versions were subsequently retired on 2026-10-14.

A no-tools invocation using contract v1 returned `insufficient_information`
with missing-source details and no findings, proposed changes or evidence.
The caller assembled a validated `AgentResult` with version 4 provenance and
model version `2026-09-22`. No wiki writes or agent identity onboarding were
performed. Hosted `documentation-agent` version 2 was not changed.

Reproduction commands and API gotchas:
[structured-output workshop guide](workshop/structured-output-guide.md).

### Gap analysis on the existing prompt agent (P1, #13)

On 2026-10-16, `doc-agent` version **3** was created using the versioned
[assessment prompt and policy](../src/agents/documentation-prompt/README.md).
Version 2 was an intermediate attempt that found the planted gaps but chose an
overly broad scope and the wrong overall status. Version 3 restricts change
reviews to the requested change, prioritizes unavailable facts when the task
requires them, and requests verbatim evidence excerpts.

The existing model, tools, approval rules, output schema and identity are retained.
Both MVP scenarios passed against version 3, including matching evidence URI,
version and excerpt to actual source-read results. No writes or approval
submissions were performed; no infrastructure or hosted-agent changes were made.
Version 1 remains the prior configuration; consumers pinned to it are unchanged.

Reproduction commands, expected results and limitations:
[gap-analysis guide](workshop/gap-analysis-guide.md). Source-bearing response
artifacts are saved only in ignored `evals/results/`.

### Hosted migration status (P1, #13; 2026-10-16)

P1 implemented the assessment inside the existing hosted Python app, per
[ADR 0024](adr/0024-hosted-documentation-runtime.md). P2 then supplied the
toolbox and permissions and deployed it: **`documentation-agent:6` runs
assessment mode against live sources** (see below). `doc-agent:3` remains the
prompt reference.

### Read-only toolbox and hosted assessment (P2; 2026-10-16)

**Toolbox** `documentation-agent-readonly`, version **1** (default), created
with [`infra/scripts/setup-toolbox.ps1`](../infra/scripts/setup-toolbox.ps1).
It reuses the existing connections and exposes only the four read tools the
runtime allows:

| Tool | Connection |
|---|---|
| `knowledge___knowledge_base_retrieve` | `kb-doc-agent-mcp` (Foundry IQ) |
| `github___get_file_contents` | `github-mcp` (GitHub read-only MCP) |
| `ado___wiki`, `ado___wit_work_item` | `ado-mcp-proxy` (gateway, agent user `documentation-agent@…`; read tools only in this toolbox) |

Endpoint (pinned to the version):
`{project-endpoint}/toolboxes/documentation-agent-readonly/versions/1/mcp?api-version=v1`.
The `ado` tools fail when called with a human token ("AgenticIdentityToken …
requires AgentInstanceClientId"): the connection only works from an agent.

**Hosted version 6**: image
`acrfoundryagenticr8n3ld.azurecr.io/documentation-agent@sha256:1a00ba37c7923b171fc13b36f16dde2592aead1e02cd5fc4fdd9ef7f75c5f863`
(tag `assessment-p2-toolbox`, built with `az acr build`), created with
`POST {project-endpoint}/agents/documentation-agent/versions?api-version=2025-11-15-preview`
(header `Foundry-Features: AgentEndpoints=V1Preview`), `kind: hosted`, 0.5 CPU,
1 GiB, protocol `responses` 2.0.0. Environment variables:

| Variable | Value |
|---|---|
| `DOCUMENTATION_MODE` / `DOCUMENTATION_AUTH_MODE` | `assessment` / `managed_identity` |
| `DOCUMENTATION_PROJECT_ENDPOINT` | project endpoint |
| `TOOLBOX_ENDPOINT` | toolbox endpoint above |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` / `DOCUMENTATION_MODEL_VERSION` | `gpt-6-luna` / `2026-09-22` |
| `DOCUMENTATION_ADO_PROJECT` / `DOCUMENTATION_ADO_WIKI` | `integration-team` / `integration-team.wiki` |
| `HOST` | `0.0.0.0` |

**End-to-end proof**: `examples/assessment-request.json` (planted-gaps commit
`ad623147`, wiki `/Order Sync/Overview`, work item 1) returned HTTP 200 in 46 s
with a contract-valid `AgentResult`: one medium finding citing DS-11 to DS-14,
seven evidence items from git, wiki and work item, all verified against the
observed tool calls. Gateway logs show `authorized caller oid=<hosted agent
identity>` for `wiki` and `wit_work_item`.

| Gotcha | Resolution |
|---|---|
| Image build failed: `src/tools` missing | The Dockerfile now copies `src/tools`, which `pyproject.toml` packages |
| `PORT` rejected as an environment variable | `PORT`, `FOUNDRY_*` and `AGENT_*` are reserved; removed |
| Version failed with `ImageError` | The **project managed identity** pulls the image: granted it AcrPull on the ACR |
| Model calls `403` | Granted the hosted agent identity **Foundry User** on `proj-agentic` |
| App Insights `403` flooding the logs | Granted the hosted agent identity **Monitoring Metrics Publisher** on `appi-foundry-agentic` |
| "ADO reads must use the configured project" | `project` is optional on `wit_work_item`; the instructions now tell the model to always pass it (the guard stays strict) |
| `JSONDecodeError` in evidence checks | GitHub returns the file as an embedded `resource`; `parse_read_result` now maps it to `documents[].content` |

Versions: `2` (stub) and `1` are kept for rollback; failed or buggy
intermediates `3` to `5` were deleted (`DELETE …/versions/{n}?force=true` when
idle sessions block it). Logs: `GET {project-endpoint}/agents/documentation-agent/versions/6/sessions/{session}:logstream?api-version=v1`.

References: [toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox),
[use a toolbox from a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent),
[deploy a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent),
[manage hosted agents](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent).

### Hosted packaging and independent smoke (P3; 2026-10-19)

Earlier P3 preparation reproduced the missing `src/tools` wheel-build failure
also fixed in P2's deployed image above. The packaging regression tests now
cover every declared package and package-data allowlist entry, including the
newer evaluation schemas. The original local full image build failed on package
host TLS; it is not the build used for P2's deployed version 6.

P3 independently observed the existing hosted-linked agent user, Principal-only
read consent, gateway federation/read role, ADO Stakeholder/Readers membership
and toolbox read filters. It did not create or reconfigure those resources.
The [preparation guide](workshop/hosted-deployment-guide.md) retains the dated
pre-cutover history; do not treat its historical empty-toolbox/admin holds as
the current state or repeat onboarding.

On 2026-10-19, the separately approved single read-only assessment ran against
unchanged concrete `documentation-agent:6` in a fresh version-bound session.
It completed with a valid v1 result and matching request/source versions,
returning four findings and two proposals with human review required.
**Contract and reviewed-source provenance checks passed**, including app version
`0.3.0`, configured model and prompt/policy hashes reconstructed from source
`2b77527`. An initial local harness false negative was resolved entirely offline:
the Windows source archive contained CRLF, while runtime `Path.read_text`
normalizes line endings before hashing. No retry, source write, runtime fix or
deployment followed. See the
[dated outcome and exact hashes](workshop/hosted-deployment-guide.md#single-approved-assessment-2026-10-19).
The [subsequent read-only telemetry lookup](#hosted-native-trace-evidence-2026-10-20)
independently correlated native model/tool spans for this same run. This result
is not a full evaluation or tool-call correctness certification.

### Approval spike status (P1, #1)

The native approval experiment is local-only, started explicitly with
`python -m documentation_agent.approval_spike --state-dir .azure\approval-spike-local`.
It writes only dummy approval records through the SDK's local state backend.
See the [walkthrough](workshop/hosted-approval-spike.md). No Azure resource,
toolbox, connection, gateway, deployed agent or Teams application was changed.
Live Toolbox integration and Teams publishing/channel verification remain pending.

### Approval write path (P2; 2026-10-20)

To keep it simple, the room chose (Rickard, Louise P3) to use the **same** hosted agent,
agent identity, agent user, gateway and connection for writes. No new agent,
gateway or connection was created.

| Step | Before | After |
|---|---|---|
| Agent user `documentation-agent@…` | Stakeholder + Readers | **Basic** + `[integration-team]\Contributors` (`onboard-agent.ps1 -AgentName documentation-agent -GatewayRole Mcp.Tools.Read.All`; the script now upgrades an existing user) |
| Delegated grant | `Ado.Mcp.Tools wit.read wiki.read` | + `wiki.write` |
| Gateway `ca-doc-agent-mcp` | `--0000005`, `ADO_MCP_READONLY=true` | `--0000006`, `ADO_MCP_READONLY=false`; role `Mcp.Tools.Read.All` and toolsets `wit,wiki` unchanged |
| Toolbox | `documentation-agent-readonly:1` (4 read tools, unchanged) | + `documentation-agent-write:1` with only `ado___wiki_upsert_page` (`setup-toolbox.ps1 -Write`) |
| Wiki | — | Operator-created parent page `/Workshop` (ADO rejects child pages without an ancestor: `WikiAncestorPageNotFoundException`) |
| Hosted agent | v7 serving (assessment) | + **v8** = v7 definition, image `documentation-agent@sha256:2093e80bea3bf6a4222b9e9982aabaefdc0b4986ae15181ec2edcbd58c9ebe65` (tag `approval-p2-sandbox`), `DOCUMENTATION_MODE=approval`, `DOCUMENTATION_ENABLE_APPROVAL=true`, `DOCUMENTATION_APPROVAL_POLICY=/app/approval/sandbox-policy.json`. **Not served**; the version selector was not changed |

The policy ([`sandbox-policy.json`](../src/agents/documentation-agent/approval/sandbox-policy.json))
is packaged in the image. It fixes the target `integration-team.wiki` `/Workshop/Approval-Sandbox`
(`wikiMaster`) and lets callers supply only `content`. The tool replaces the whole page;
`etag` is not set, so the server fetches the current one (last writer wins; see #21).

**Hosted E2E (2026-10-20, version-specific sessions on v8):**

| Step | Response ID | Result |
|---|---|---|
| Propose (session `045c4db1…`) | `caresp_03c6c09aee19557100Lf5qYj5Q4ZR1JezjoN3qGcB5MpbhkHD5` | `mcp_approval_request`; page still 404 |
| Reject | `caresp_03c6c09aee19557100oDOnUJnTuIJVlKJ0ROREfOmOO6q7aKsD` | `rejected`; page still 404, no `tools/call` |
| Propose (session `020c3517…`) | `caresp_08c13add1e3aaa9400YaFnA5v1C9lI1tUZ3Hmf1xGkdmbdTf0F` | `mcp_approval_request`; page still 404 |
| Approve | `caresp_08c13add1e3aaa9400iiJ2YkvBaRCEPRy1FOf6Gs9wZkVA7kaa` | `succeeded`; exactly one gateway `tools/call tool=wiki_upsert_page` (08:10:35Z) |

Page readback: 404 before, then ETag `b0cf2b88b8fbc7bc9803da5d08b495ece77d8832` with the
approved content. The wiki commit `ca622ad0cf` is authored by
`documentation-agent@M365CPI54615665.onmicrosoft.com`. One earlier approval
(`caresp_01e6a6a8d2846b5400vI3tQ5mRLFXzL816Wj0svlNP676E5wp0`, before `/Workshop`
existed) ended `outcome_unknown` as designed. Reconciliation showed no write; the
runtime logs do not include the tool's error text, which made the cause harder to find.

## Outputs (environment values)

Store these in a local `.env` (git-ignored). Never commit secrets; prefer Entra ID auth over keys.

| Variable | Value / where to find it |
|---|---|
| `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
| `AZURE_TENANT_ID` | `az account show --query tenantId -o tsv` |
| `AZURE_RESOURCE_GROUP` | `rg-foundry-agentic-pattern` |
| `AZURE_LOCATION` | `swedencentral` |
| `FOUNDRY_PROJECT_ENDPOINT` | `https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic` |
| `CHAT_MODEL_DEPLOYMENT` | `gpt-6-luna` |
| `EVAL_MODEL_DEPLOYMENT` | `eval-gpt-5.4-mini` (deployed 2026-10-20, `NoAutoUpgrade`) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | **Not required for MVP native server-side tracing**; do not retrieve or commit it |
| `COSMOS_ENDPOINT` | **Not required for MVP**; Cosmos DB deferred |
| `AZURE_DEVOPS_ORG_URL` | `https://dev.azure.com/foundry-agentic` |
| `AZURE_DEVOPS_PROJECT` | `integration-team` |

## Change log

| Date | Who | Change |
|---|---|---|
| 2026-10-16 | Louise / Copilot | Applied explicitly approved native monitoring setup: workspace + workspace-based Entra-only App Insights in Sweden Central, 30-day workspace/table retention, project-MI scoped ingestion role and connection. Verified one no-tools `doc-agent:3` assessment through correlated native agent/model spans; no model or agent/routing edits |
| 2026-10-16 | Louise / Copilot | Read-only WSL CLI inventory: recorded model versions, auto-upgrade policies, rate limits, quota discrepancy and missing monitoring connection; added repeatable inventory and approval-gated model/native-tracing procedures (#5, #49, native subset of #9). No cloud writes or invocation/ingestion verification |
| 2026-10-16 | John | Configured `doc-agent:3` with versioned assessment instructions; both MVP scenarios passed contract, expected findings/status and source-read evidence checks (#13) |
| 2026-10-13 | John | Confirmed P1 MVP scope; configured `doc-agent-spike` v4 with native structured output and demonstrated validated contract v1 without tools (#12) |
| 2026-10-08 | John | Built and deployed `documentation-agent` hosted stub v2 from the existing ACR; verified valid and invalid contract requests remotely (#7) |
| 2026-10-07 | Rickard | Resource group, Foundry resource + project created |
| 2026-10-08 | Rickard | Azure DevOps org/project/wiki created and connected to the tenant; shared environment documented |
| 2026-10-08 | Rickard | Agent identity → Azure DevOps end to end: agent user, consent grant, MI + blueprint federated credential, gateway app, ACR, Container App (North Europe), Foundry connection `ado-mcp-proxy`, agent v3 ([ADR 0021](adr/0021-agent-user-and-ado-mcp-gateway.md)) |
| 2026-10-08 | Rickard | `onboard-agent.ps1` verified with a temporary agent `doc-agent-test` (onboarded, E2E read + approved wiki write, then offboarded); gateway points back at `doc-agent-spike` |
| 2026-10-14 | Rickard | Inventoried resources, connections and identities into the [resource organisation guide](workshop/resource-organization-guide.md) (#45); deleted the failed, empty Container Apps environment `cae-foundry-agentic` (Sweden Central) |
| 2026-10-14 | Rickard | `doc-agent-spike:7` via `setup-foundry-iq.ps1`: the documentation standard is cited by rule ID, not as evidence; "Information missing" scenario added ([guide](workshop/information-missing-guide.md), #32) |
| 2026-10-14 | Rickard | Final RBAC matrix checked against the environment ([architecture §6](architecture.md#6-identity--rbac-matrix)); [bring-your-own guide](workshop/bring-your-own-guide.md) for your own sources and standard (#36) |
| 2026-10-14 | Rickard | Prompt agent `doc-agent:1` created as a copy of `doc-agent-spike:7` (same model, tools and instructions) and onboarded with `onboard-agent.ps1`; the gateway now points at `doc-agent`. Planted-gaps scenario `PASS`; information-missing scenario `PASS` on 2 of 3 runs (see [evals](../evals/README.md)). P2 is demoed on `doc-agent` in the playground |
| 2026-10-14 | Rickard | Offboarded `doc-agent-spike`: Azure DevOps entitlement removed, agent user deleted, agent deleted (its identity and blueprint go with it). Agents in `proj-agentic`: `doc-agent`, `documentation-agent` |
| 2026-10-16 | Rickard | Read-only gateway cutover to the hosted `documentation-agent` (P3 request, ADR 0024) with `onboard-agent.ps1 -ReadOnly`: agent user `documentation-agent@…` (Stakeholder + Readers), grant `Ado.Mcp.Tools wit.read wiki.read`, new app role `Mcp.Tools.Read.All`, gateway revision `--0000005` with `ADO_MCP_READONLY=true`. `doc-agent`'s grants are kept for rollback; its `ado` tool now gets `403`. Hosted runtime proof pending |
| 2026-10-16 | Rickard | Read-only toolbox `documentation-agent-readonly:1` (`setup-toolbox.ps1`); hosted identity granted Foundry User and Monitoring Metrics Publisher, project MI granted AcrPull. Deployed `documentation-agent:6` in assessment mode; end-to-end assessment passed through the toolbox and gateway. Fixed the Dockerfile, the ADO `project` instruction and GitHub resource parsing. Deleted versions 3–5 |
| 2026-10-20 | Rickard | [Approval write path](#approval-write-path-p2-2026-10-20) (room decision, P3 approved): `documentation-agent@…` → Basic + Contributors, grant + `wiki.write`, gateway `--0000005` → `--0000006` with `ADO_MCP_READONLY=false`, toolbox `documentation-agent-write:1` (`wiki_upsert_page` only), parent page `/Workshop`, unserved approval version `documentation-agent:8`. Hosted propose/reject/approve proven against `/Workshop/Approval-Sandbox`; selector untouched (v7) |
| 2026-10-22 | Rickard | Playground demo for P2: toolbox `p2-demo-toolbox:1` (Foundry IQ `knowledge_base_retrieve` + GitHub `get_file_contents`/`pull_request_read`, read-only, no ADO), RemoteTool connection `p2-demo-toolbox` (user Entra token) and prompt agent `p2-demo-agent:3` (`gpt-6-luna`). Removed `demo-foundry-iq.ps1` and `demo-toolbox.ps1`. After John's chat change (#114), the P2 demos run in the playground on hosted `documentation-agent:26`; both questions verified through its Responses endpoint. `p2-demo-agent` is the fallback |
| 2026-10-23 | Rickard | Project connection `srch-foundry-agentic-r8n3ld` (CognitiveSearch, Entra ID, no key) to AI Search so the portal's Knowledge page lists `kb-doc-agent` and index `doc-knowledge`; the KB was script-created and had only the MCP tool connection. Agents unchanged. P2 demo proof views: Agents → Traces (tool spans), gateway Log stream (caller `oid`), served version `documentation-agent:29` |
| 2026-10-23 | Rickard | `kb-doc-agent` and `ks-doc-knowledge` descriptions now say what is indexed (the documentation standard, DS-01 to DS-31), where it comes from (`data/knowledge/` in GitHub, pushed by `setup-foundry-iq.ps1`, no indexer) and why (stable rules cited by ID; volatile data stays live through the toolbox). Retrieval instructions not set: the API requires a KB model, and the KB runs `minimal` without one (ADR 0022) |
| 2026-10-23 | Rickard | `kb-doc-agent` → retrieval effort `low` with model `eval-gpt-5.4-mini` (shared with the evaluator) and retrieval instructions; search service identity granted Cognitive Services User on `foundry-agentic-R8N3LD`. Replaces `minimal` without a model (ADR 0022). Retrieve shows `modelQueryPlanning` and three subqueries; both P2 demo questions re-verified on `documentation-agent:29`. Agent unchanged |
| 2026-10-23 | Rickard | Toolbox `documentation-agent-readonly:4` (default): same five read tools as v2, with descriptions that say what each source reads and how (Foundry IQ via the project identity; ADO through gateway `ca-doc-agent-mcp` as the agent identity). Toolbox versions are immutable, so the text needed a new version; v3 was created with a typo and deleted. `setup-toolbox.ps1` now sets the new version as default. `documentation-agent:30` = v29 with all three read-toolbox variables (`TOOLBOX_ENDPOINT`, `DOCUMENTATION_PUSH_READ_TOOLBOX`, `DOCUMENTATION_CHAT_READ_TOOLBOX`) on v4; assessment was on v1, which lacks the `repo_file` tool the runtime requests. Selector → v30 at 100%; v29 kept for rollback. All three P2 questions verified, trace shows `tools/list documentation-agent-readonly:4`. Deleted the unused `p2-demo-agent`, toolbox `p2-demo-toolbox` and connection `p2-demo-toolbox` |
