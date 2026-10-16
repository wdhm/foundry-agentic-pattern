# Manual setup runbook

> **Why manual?** [ADR 0020](adr/0020-manual-setup-first.md): during M0–M3 we set up Azure by hand. This runbook is the **single source of truth** for the environment, and it gets codified as `azd` + Bicep in M4 ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).
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
Historical hosted-agent deployment instructions below are unchanged.

- [x] Resource group `rg-foundry-agentic-pattern` in Sweden Central
- [x] **Foundry resource** `foundry-agentic-R8N3LD` + **Foundry project** `proj-agentic`
- [ ] **Model deployments**: one **chat** model (agent) and one **eval** model (evaluators). Chat exists but is not pinned; separate eval deployment is absent. See the dated inventory and approval gates below.
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

**Still open:** full #9's custom dimensions/Cosmos correlation are explicitly
deferred, not completed. This single no-tools assessment does not prove
tool-operation tracing, all-owner access, hosted-stub tracing, or release routing.

### Handoff to eval/release work

Do not mark the cloud setup complete until these outputs are supplied:

| Output | Current value / required evidence |
|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | Existing endpoint in Outputs below |
| Agent selector | `doc-agent`; observed latest version `3` on 2026-10-16. Re-read latest; choose an explicit tested version, not the hosted stub or retired spike |
| `CHAT_MODEL_DEPLOYMENT` / model version | `gpt-6-luna` / `2026-09-22`; currently auto-upgrades, so record the observed version per eval run |
| `EVAL_MODEL_DEPLOYMENT` / model version | **Unset** until model compatibility, quota, cost and deployment approval are resolved |
| Capacity evidence | Fresh regional quota + deployment rate limits; resolve chat `current=500`, `limit=250` discrepancy |
| Tracing destination | `appi-foundry-agentic` / workspace `log-foundry-agentic`; project `AppInsights` / `ProjectManagedIdentity` connection and project-MI ingestion role verified |
| Native trace proof | Successful correlated agent/model spans above; exact UTC, agent/model versions, Response ID, Conversation ID, Trace ID and query result recorded. Portal UI not visually verified |
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
| **AI Gateway (APIM)**: token limits + FinOps tagging | [#3](https://github.com/wdhm/foundry-agentic-pattern/issues/3), [#23](https://github.com/wdhm/foundry-agentic-pattern/issues/23) | P3; deferred from the approved platform-first MVP |
| Hosted agent deployment | [#7](https://github.com/wdhm/foundry-agentic-pattern/issues/7) | P1 |
| Teams / M365 publish | [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4) | P3 |

Document each step here when you do it: portal path or CLI command, settings chosen, and any gotchas.

### Hosted contract stub (P1, #7)

`documentation-agent` version **2** is active in `proj-agentic`. It runs the
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
| Agent user | `doc-agent@M365CPI54615665.onmicrosoft.com` | Linked to the agent identity. Azure DevOps **Basic** + `[integration-team]\Contributors` |
| Consent grant | Agent identity → **Azure DevOps MCP** (`2a72489c-…`), consentType `Principal` (agent user) | Scopes `Ado.Mcp.Tools wit.read wiki.read wiki.write`. We created the Azure DevOps MCP service principal in the tenant. |
| User-assigned MI | `id-doc-agent-mcp` | Federated credential `mcp-server-uami` on the agent's **blueprint**; AcrPull on the ACR |
| Gateway Entra app | `doc-agent-mcp-api` (`api://<appId>`) | App role `Mcp.Tools.ReadWrite.All`, assigned to the agent identity |
| Container registry | `acrfoundryagenticr8n3ld` (Basic, Sweden Central) | Image `ado-mcp:0.2.1` |
| Container Apps env | `cae-doc-agent-mcp` (**North Europe**) | Sweden Central had no capacity (`AKSCapacityHeavyUsage`); logs: console only |
| Container app (gateway) | `ca-doc-agent-mcp` | `https://ca-doc-agent-mcp.gentlemushroom-65b5f1ef.northeurope.azurecontainerapps.io/mcp` |
| Foundry connection | `ado-mcp-proxy` | `RemoteTool`, `AgenticIdentityToken`, audience `api://<gateway appId>` |

To onboard another agent, run [`infra/scripts/onboard-agent.ps1`](../infra/scripts/onboard-agent.ps1) ([guide](workshop/agent-identity-guide.md#onboard-another-agent-automated)). The gateway serves one agent at a time and currently points at `doc-agent`.

### Structured-output contract demo (P1, #12)

**Current target:** use the prompt agent `doc-agent` (version 1 in the
2026-10-14 inventory), not `doc-agent-spike`, which was offboarded and deleted.
The current agent was copied from spike version 7 and includes the structured
output schema plus P2's `knowledge`, `github` and `ado` tools. Inspect its latest
version before any configuration change; do not recreate the retired spike.
The version 4 result below is historical verification, not a current endpoint.

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

P1 is implementing the assessment inside the existing hosted Python app, per
[ADR 0024](adr/0024-hosted-documentation-runtime.md). The application has an
opt-in v1 assessment mode and retains the v0 stub default. Its new code has
only been checked locally with model/tool doubles, not deployed.

A read-only toolbox inventory returned no toolbox resources in `proj-agentic`.
The existing source connections alone do not supply a toolbox MCP endpoint.
P2 must provide that endpoint and verify the hosted identity's source/model
access. The [hosted README](../src/agents/documentation-agent/README.md)
specifies the four read tools and runtime configuration.

No toolbox, connection, permission or gateway change was made during local
hosted implementation. `doc-agent:3` continues working as the prompt reference;
deployed `documentation-agent:2` is still the stub. Do not count the prompt
agent's earlier scenario passes as hosted migration acceptance.

### Hosted deployment preparation (P3; 2026-10-16)

Read-only preflight against main `1ddaec87` confirmed hosted version **2** and
prompt version **3** remain active/latest. Both named endpoints still select
`@latest` at 100%, with Responses, Entra authorization and `not_published`.
No version, serving selector, identity, connection, gateway, model or publication
was changed, and no remote invocation was made.

The successful toolbox `v1` API inventory is empty. The ADO gateway's configured
identity and blueprint still belong to `doc-agent`, not the hosted agent.
Meaningful hosted assessment is **blocked** on P2 toolbox/source authorization
and coordinated serving isolation; deploying the default stub is not a substitute.
Existing connections alone do not meet those prerequisites.

Local image preparation reproduced and fixed a packaging failure: `pyproject.toml`
declares `src/tools`, but the Docker build inputs omitted it. The Dockerfile and
allowlist now include that package. The corrected inputs produce a wheel with
all packages and assessment prompt/policy data. A full local container build
remains unverified because container pip encountered a TLS handshake failure;
do not bypass certificate checks or substitute an Azure build while blocked.

The bounded plan, exact prerequisites, build limitations, approval gates and
future smoke contract are in the
[hosted deployment preparation guide](workshop/hosted-deployment-guide.md).
The canonical execution plan and subscription/tenant identifiers stay in the
deployment owner's ignored `.azure/deployment-plan.md`. It is not validated or
approved for execution.

The user subsequently accepted transitioning the existing ADO gateway from the
prompt agent to the hosted agent's own identity/user, including prompt ADO
interruption. The proposed least-privilege grants, existing gateway settings,
single reusable toolbox, operator-authority requirements and rollback are in the
same guide. The user approved that configuration-only plan and accepted an ADO
access gap until hosted deployment and authorized immediate cutover timing.
Execution remains **held on supported authorized admin execution**; Azure remains unchanged. Hosted version 2
is still a stub, so actual hosted tool access also requires separately approved
assessment runtime verification.

### Approval spike status (P1, #1)

The native approval experiment is local-only, started explicitly with
`python -m documentation_agent.approval_spike --state-dir .azure\approval-spike-local`.
It writes only dummy approval records through the SDK's local state backend.
See the [walkthrough](workshop/hosted-approval-spike.md). No Azure resource,
toolbox, connection, gateway, deployed agent or Teams application was changed.
Live Toolbox integration and Teams publishing/channel verification remain pending.

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
| `EVAL_MODEL_DEPLOYMENT` | **Unset**: no separate eval deployment observed 2026-10-16; approval/quota decision pending |
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
