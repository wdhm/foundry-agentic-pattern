# Optional AI gateway: governance without replacing the agent

An Azure API Management (APIM) AI gateway is a good **additional** platform
boundary: it can authenticate callers, constrain model selection and usage, and
throttle access to a versioned toolbox. It cannot determine whether an answer is
supported by sources or whether a human approved the exact write.

**Repository preparation; no deployment or routing proof is recorded here.**
The user approved a public, model-only Developer demo on 2026-10-21.
Tool/agent routes remain future opt-ins, not part of that initial deployment.
This reopens the earlier slides-only disposition in ADR 0022; it does not turn
the workshop into a production platform. See
[ADR 0027](adr/0027-opt-in-ai-gateway.md).

## Initial demo: public HTTPS, model routing only

The approved starting architecture is one **Developer** unit in **Sweden
Central**, public HTTPS, no VNet, private endpoint, VPN or WAF. The user approved
the quoted **USD 0.0658/hour (~USD 48.03 per 730 hours)** configuration.
This is a time-specific retail estimate, not a billing guarantee; log ingestion/
retention and model usage are additional. Developer has **no production SLA**.
Provider registration, capacity, deployment and live acceptance remain operator
steps; this document is not evidence that they happened.

The intended demo context is subscription
`ac021984-29ca-42e6-9c21-36e599814543`, resource group
`rg-foundry-agentic-pattern`, candidate service `apim-foundry-agentic-r8n3ld`.
The parent coordinator owns final merge and Azure execution. Publisher
organization/contact, exact caller object ID, deployment pin and positive
`tokensPerMinute`/`dailyTokenQuota` values must be explicitly reviewed before
execution; this repo invents neither personal contact details nor usage budgets.

Three separate templates keep paid service creation, telemetry destination and
route configuration independently reviewable:

| Step | Template and inputs | Scope |
|---|---|---|
| Public demo bootstrap | [`bootstrap-public-developer.bicep`](../infra/ai-gateway/bootstrap-public-developer.bicep): required `apimName`, `location`, `publisherName`, `publisherEmail` | Creates only one public Developer unit with a system-assigned identity. No API routes, logger, role assignments or runtime opt-ins. |
| Existing-workspace telemetry and admission baseline | [`azure-monitor-diagnostics.bicep`](../infra/ai-gateway/azure-monitor-diagnostics.bicep): required `apimName`, `logAnalyticsWorkspaceName` | Installs global default-deny, explicitly creates credential-free logger `azuremonitor` of type `azureMonitor`, then global zero-body/empty-header diagnostics and **GatewayLogs only** to the existing workspace's resource-specific table. No role assignment, connection string, new workspace or generative-AI payload log category. |
| Model-only configuration | [`main.bicep`](../infra/ai-gateway/main.bicep): required `apimName`, `projectEndpoint`, `tenantId`, `callerObjectId`, `loggerResourceId`, `modelDeployment`, `tokensPerMinute`, `dailyTokenQuota`; explicitly set `diagnosticType=azuremonitor` and `enableToolRouting=false`, omit both toolbox inputs | Creates only the model API/policy, model/common named values and zero-body/empty-header Azure Monitor API diagnostics. No tool API/operations/policy/diagnostics/counter/rate values; no agent ingress deployment or runtime change. |

`loggerResourceId` comes from the Azure Monitor module output, not the bootstrap.
This is an explicitly selected supported sink, **not** an unlogged/key-auth
fallback; no new APIM-identity RBAC grant is needed. The alternative Application
Insights managed-identity logger remains available but its new telemetry grant
is still pending permission and is **not needed for this initial path**.
Do not enable traffic without verified working diagnostics. The nullable
`toolboxGatewayEndpoint` output is **null** for model-only configuration.
Omitting the toolbox URL also defaults to model-only; old callers supplying the
original toolbox URL and positive request limit still get their two-route
configuration. Enabling tools without both inputs fails explicitly rather than
inventing a URL or quota. Conditional resources in an **incremental** deployment
omit creation/update; they do not delete tool APIs from an earlier installation.
If reusing an instance, inventory existing routes before claiming model-only
coverage. The recorded demo inventory found no APIM instance.

Prepare reviewed ARM parameter files under ignored `.azure/` locally. After
the coordinator completes Azure preflight, the first explicit execution step
is (this command **creates a paid resource**, not a local check):

```powershell
az deployment group create --subscription ac021984-29ca-42e6-9c21-36e599814543 `
  --resource-group rg-foundry-agentic-pattern --name apim-public-bootstrap `
  --template-file .\infra\ai-gateway\bootstrap-public-developer.bicep `
  --parameters '@.azure/apim-bootstrap.parameters.json'
```

Use `apimName=apim-foundry-agentic-r8n3ld`, `location=swedencentral` and the
operator-confirmed publisher organization/contact in that ignored parameter
file; no public-repo personal contact is provided. Wait for successful service
provisioning. Prepare the monitor parameters with that APIM name and
`logAnalyticsWorkspaceName=log-foundry-agentic`, then run:

```powershell
az deployment group create --subscription ac021984-29ca-42e6-9c21-36e599814543 `
  --resource-group rg-foundry-agentic-pattern --name apim-gateway-telemetry `
  --template-file .\infra\ai-gateway\azure-monitor-diagnostics.bicep `
  --parameters '@.azure/apim-monitor.parameters.json'
```

After telemetry configuration and built-in logger availability have been verified,
configure the model-only route with the exact inputs above:

```powershell
az deployment group create --subscription ac021984-29ca-42e6-9c21-36e599814543 `
  --resource-group rg-foundry-agentic-pattern --name apim-model-configuration `
  --template-file .\infra\ai-gateway\main.bicep `
  --parameters '@.azure/apim-model.parameters.json'
```

### Fresh-service recovery and default-deny gate

On 2026-10-22 the operator reported that the Developer service was provisioned,
but monitor setup failed with **`Logger Id 'azuremonitor' does not exist`**.
The workspace export setting succeeded independently; that partial success is
not a working logger/global diagnostic or permission to deploy model routes.
The earlier PowerShell example retrieved an existing logger and did not
establish that a fresh service creates it automatically.

The corrected monitor template explicitly creates `service/loggers/azuremonitor`
with **`loggerType: 'azureMonitor'`**, without credentials, target resource ID,
keys or grants. The [2024-05-01 Logger Create Or Update contract](https://learn.microsoft.com/rest/api/apimanagement/logger/create-or-update?view=rest-apimanagement-2024-05-01)
documents the PUT API, the `azureMonitor` enum and optional credentials.
The global diagnostic references the declared logger's ID, making logger
creation an ARM dependency. Re-run the corrected **monitor template only** with
the same reviewed service/workspace parameters after new validation/what-if.
Its stable resource names also update the already-created GatewayLogs setting;
do not recreate the paid service or switch to Application Insights key auth.

The provider also seeded a subscription-protected Echo API despite the
service-only template declaring no APIs. Setup now installs a **global inbound
403 `return-response` policy before logger/export configuration**, without
deleting Echo or changing its subscription setting. The supported
[`return-response` policy](https://learn.microsoft.com/azure/api-management/return-response-policy)
cancels pipeline execution, preventing inherited/unconfigured routes from
forwarding, including a newly created model API before its API policy exists.
The reviewed model policy deliberately omits `<base/>` in every section and is
the explicit JWT-authenticated override, retaining all its original controls.

Inspect effective policies at product/API/operation scopes, including seeded
Echo, and verify denied requests do not reach a backend. A pre-existing policy
that omits inheritance can override a global rule; this is not proof against
arbitrary administrator-created routes. This template owns/replaces the
service-global policy, so review conflicts before using it on a shared instance.
Keep the service-only bootstrap unchanged. Require **complete** setup success,
confirmed logger type, default-deny/effective-policy checks and the existing
privacy/ingestion acceptance before model configuration/traffic; a failed or
partially successful setup remains closed to rollout.

Before bootstrap, verify/register `Microsoft.ApiManagement` in that exact
subscription through the approved operator workflow; do not change CLI defaults.
The deployer needs APIM/diagnostic configuration and existing-workspace
destination permissions, not role-assignment permission for this Azure Monitor
path. Verify provisioning, built-in logger availability, ingestion and
body-free diagnostics, then
test admission/model/limit behavior using an explicitly reviewed client identity.
Only after that validation should a separately reviewed runtime candidate add
**`DOCUMENTATION_MODEL_GATEWAY_ENDPOINT` alone**. Keep the Toolbox setting and
CLI agent-ingress flag unset; do not republish Teams or change write/approval
transport. A template deployment alone does not route the hosted application.

This manual SDK route works with the documented classic Developer policy
support. It is **not** a Foundry portal-native AI gateway association, which
requires an eligible **v2** instance. Do not try to associate this Developer
instance with the project or enable wider native project routing.

### Native Foundry UI: separate v2 association and project activation

The user subsequently approved a **new Basic v2** gateway for native Foundry
visibility. This does not convert the classic Developer deployment or authorize
deleting it. Microsoft's [v2 overview](https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview)
states that upgrading a classic instance to v2 is unavailable. The
[regional availability table](https://learn.microsoft.com/azure/api-management/api-management-region-availability)
lists Basic v2 in Sweden Central; actual subscription capacity must still pass
preflight. Budget for ordinary Basic v2 charges (the reviewed estimate was
approximately USD 197/month) **plus** the retained Developer, model usage and log
ingestion. Do not assume that a Foundry free allowance waives these charges.

Use the [documented native Foundry workflow](https://learn.microsoft.com/azure/foundry/configuration/enable-ai-api-management-gateway-portal),
not a generic project connection or our `/documentation-model/` API:

1. Complete preparation, validation and source review before paid execution.
   Confirm the same approved subscription/tenant and a signed-in **New Foundry**
   browser. If browser access is unavailable, hold creation rather than provision
   another standalone service that cannot satisfy native UI acceptance.
2. In **Manage > AI Gateway > Add AI Gateway**, choose the **Foundry resource**
   `foundry-agentic-R8N3LD`. Select **Create new** for the documented Basic v2
   creation path, or **Use existing** for a separately prepared eligible v2
   instance. The proposed separate name is `apim-foundry-agentic-v2-r8n3ld`;
   recheck availability at execution time.
3. Select **Add** and verify the correct resource's gateway actually appears
   **Enabled** in the UI. Capture resource IDs, SKU, location, association and
   provisioning evidence locally. An APIM ARM deployment alone does not prove
   native association or UI visibility.
4. Open its project list and verify existing `proj-agentic` remains **Disabled**.
   **Do not select Add project to gateway** under the resource-visibility-only
   authorization. Existing-project enablement is a separate model-routing switch;
   new projects inherit gateway enablement by default, so do not create a test
   project as an acceptance shortcut.

The official guide requires Contributor/Owner to create APIM, appropriate
APIM Service Contributor/Owner access to reuse it, and Foundry **Manage** access.
Those examples are permission prerequisites, not authorization to grant new roles.
Inspect any proposed identity/role changes before confirming them. A browser
handoff must explicitly pause the automation writer; do not run competing portal
and ARM writers.

As of the bounded 2026-10-22 review, the native guide documents a portal operation,
not a public association REST/CLI contract. The public CognitiveServices schema's
`ApiManagement` and `ModelGateway` connection categories do not establish such a
contract. Do not invent connection metadata or use a different
`Microsoft.ApiManagement/aigateways` resource as a substitute. This is a
**documented-workflow/browser-access dependency**, not proof that programmatic
association is technically impossible. Revisit only with an official supported
contract or a signed-in native workflow.

Before any later project activation, inventory native-created APIs, operations,
policies, backend authentication, identities and all diagnostic sinks. Preserve
zero request/response body bytes, empty logged headers, `logClientIp=false`,
Azure Monitor information/100% sampling and **GatewayLogs-only** export to the
existing workspace. Review default-deny inheritance and explicit route overrides:
our monitor module **owns/replaces** the global policy, while native setup may
install its own policies. Do not blindly reapply it over native-managed resources
or assume native routes satisfy the standalone exact-caller/model/schema guards.
Resolve any compatibility gap through reviewed source before routing traffic;
never weaken admission, privacy or approval semantics to make the UI work.

Resource-level UI visibility can be accepted with project traffic still disabled.
That result does **not** establish inference, tool or agent governance through the
new service. Keep existing hosted serving/image/model and direct settings
unchanged; tools, agent ingress, Teams and approved writes stay direct. Project
activation, bounded inference acceptance, and retirement of the old service each
require their own explicit execution decision. Disabling a project does not stop
APIM charges.

## Three different traffic paths

| Path | Opt-in integration | What it does not cover |
|---|---|---|
| Hosted assessment -> model | `DOCUMENTATION_MODEL_GATEWAY_ENDPOINT` routes the existing Foundry client's OpenAI **Responses model-inference API** through APIM. Applies to assessment, live-source evaluation, supplied-source evaluation, and the assessor in the push-to-Teams flow. | Foundry service-side built-in evaluator calls, old prompt agents, other applications, and traffic that retains direct configuration. |
| Hosted assessment -> Foundry Toolbox -> existing ADO gateway / GitHub / knowledge | `DOCUMENTATION_TOOLBOX_GATEWAY_ENDPOINT` routes read-toolbox MCP transport through APIM. Exact backend toolbox version is set in the infrastructure, not selected by callers. | APIM does not replace the toolbox, parse per-tool permissions, exchange delegated ADO identity, or become a new ADO gateway. Write-toolbox calls stay direct. |
| CLI -> Foundry hosted assessment agent | `--agent-gateway-endpoint` opts the final named-agent Responses request into a separately configured APIM ingress API. Session creation and GET-confirmed concrete version binding remain direct and unchanged. | Teams Activity, pipeline push/Invocations transport, approval decisions/writes, session control, selectors and fleet-wide governance are not routed by this CLI opt-in. |

The first row's `/responses` is **model inference**, not the third row's
version-bound hosted-agent session API. Pointing a project or agent endpoint at
a generic proxy would conflate these paths and their identity/session semantics.

## Optional hosted-agent Responses ingress

This is technically feasible with supported interfaces; its initial omission
was a staging choice, **not** a demonstrated Foundry/APIM incompatibility.
The official [`AIProjectClient.get_openai_client` reference](https://learn.microsoft.com/python/api/azure-ai-projects/azure.ai.projects.aiprojectclient?view=azure-python#azure-ai-projects-aiprojectclient-get-openai-client)
documents `agent_name`, the named-agent
`{project}/agents/{name}/endpoint/protocols/openai` endpoint, an explicit
`base_url` override, and the renewable `https://ai.azure.com/.default`
bearer provider. The implementation retains `agent_name` when overriding the
URL, so SDK-generated Foundry feature headers and identity remain intact.
The CLI explicitly opts into the documented named-agent preview contract only
when this flag is used; this is not a new general-availability/SLA claim.

After separately approving/configuring
[`agent-ingress.bicep`](../infra/ai-gateway/agent-ingress.bicep), append this to
the existing reviewed hosted CLI invocation (keep its artifact, exact agent/
model version, source and task arguments):

```text
--agent-gateway-endpoint https://<apim-name>.azure-api.net/documentation-agent/
```

This module is independent of `main.bicep`: it requires the existing `apimName`,
`loggerResourceId`, HTTPS `projectEndpoint`, fixed `agentName`, `tenantId`,
`ingressCallerObjectId` and positive `requestsPerMinute`. The ingress caller is
the **client's object ID**, not the hosted identity used for outbound model/tool
calls. No token is exchanged for APIM's identity and no new grant is created.

Only `POST /responses` exists, bound to the reviewed named-agent backend.
Its schema requires a nonempty `agent_session_id` and string `input`; only
`store` and `stream` are additionally accepted. There are no wildcard paths,
agent overrides, session-control operations, native approval input arrays or
`previous_response_id` continuations on this route. The CLI still validates the
hosted assessment artifact/model and creates/GET-verifies the exact version
session directly **before** sending the unchanged session ID and request.
Response reference/provenance checks and the truthful
`version_specific_session_not_serving_path_proof` report stay unchanged;
The optional `response_transport: apim_agent_ingress` field records only an
opted-in route; the direct report shape is unchanged.
APIM adds admission and HTTP rate control, not independent version certification;
Foundry session authorization and existing caller/runtime checks remain required.

The ingress policy validates the original client bearer identity and aggregates
HTTP requests for this fixed agent route. It does **not** apply model token
accounting to agent output, retry, follow backend redirects, substitute identities,
rewrite payloads or buffer response chunks. See the official
[`forward-request` contract](https://learn.microsoft.com/azure/api-management/forward-request-policy).
The client also disables automatic OpenAI retries in this opt-in. Removing the
CLI flag restores the existing direct path; gateway failures never bypass it.
This is a read-only assessment transport surface, **not** a new
approval-resume or Teams/push adapter. Live named-endpoint/session compatibility,
timeouts and streaming still require isolated, separately approved validation.

## Runtime configuration

Keep every existing project, model/version, source and toolbox setting. Add
either or both settings to a **separately reviewed candidate**:

```dotenv
DOCUMENTATION_MODEL_GATEWAY_ENDPOINT=https://<apim-name>.azure-api.net/documentation-model/
DOCUMENTATION_TOOLBOX_GATEWAY_ENDPOINT=https://<apim-name>.azure-api.net/documentation-tools/mcp?api-version=v1
```

Omitting both settings preserves direct mode, including its existing SDK retry
behavior. Invalid opt-in URLs fail settings validation; a gateway error is
propagated, never silently bypassed. In gateway model mode the OpenAI client's
automatic retries are disabled. The evidence-repair attempt remains an explicit
application-level analysis step, not a network retry.

The pinned `agent-framework-foundry==1.13.1` `FoundryChatClient` obtains an
`AsyncOpenAI` client from `AIProjectClient.get_openai_client()`. The integration
changes only that client's public `base_url` and `max_retries` properties before
use. It retains Foundry-specific request/tool handling, capture middleware and
the renewable token provider. Both model inference and `FoundryToolbox` request
`https://ai.azure.com/.default`. The gateway validates that audience, tenant,
signature, expiry and **configured caller object ID**, then forwards the original
bearer token. The caller still needs its existing Foundry authorization.
There are no subscription keys, APIM managed-identity substitution, new grants or
changes to the ADO agent-user exchange. Local `azure_cli` testing would need the
reviewed developer's object ID instead; never widen the hosted allowlist to a
tenant-wide rule to make a local test pass.

## Infrastructure and enforcement

[`infra/ai-gateway/main.bicep`](../infra/ai-gateway/main.bicep) configures a model
API and an optional tools API on an **existing, separately approved APIM instance**, plus named values,
policies and body-free diagnostics using the explicitly selected existing logger.
It does not create an APIM service, logger, Foundry resource, identity or RBAC
assignment; it is not wired into CI or the existing release/deployment scripts.

| Configuration | Review requirement |
|---|---|
| `apimName`, `diagnosticType`, `loggerResourceId` | Existing instance, selected diagnostic type and matching logger resource ID. `diagnosticType` defaults to `applicationinsights` for compatibility; initial demo explicitly uses `azuremonitor`. Fixed API/named-value names mean one reviewed project/caller per instance; do not overwrite another installation. |
| `projectEndpoint` | Exact HTTPS Foundry project endpoint, no trailing slash; must equal the candidate's `DOCUMENTATION_PROJECT_ENDPOINT`. |
| `enableToolRouting`, `readToolboxBaseUrl` | Initially `false` and omitted, respectively. Future tools opt-in: exact HTTPS versioned **read-only** Foundry Toolbox URL ending `/toolboxes/<name>/versions/<number>`, no `/mcp`, query or trailing slash. Must correspond to the candidate's direct `TOOLBOX_ENDPOINT`. Never target the write toolbox or the ADO gateway directly. |
| `tenantId`, `callerObjectId` | Reviewed tenant and calling managed identity's **object** ID, not its client ID or a caller-supplied agent-name header. |
| `modelDeployment` | Same deployment as `AZURE_AI_MODEL_DEPLOYMENT_NAME`; preserve/review its concrete `DOCUMENTATION_MODEL_VERSION` and evaluator pins independently. |
| `tokensPerMinute`, `dailyTokenQuota`, `toolRequestsPerMinute` | First two always required and positive; tool request limit required only when tools are enabled. No production budget or capacity is chosen by default. Token counters aggregate this route's project/deployment; tool counters aggregate the configured toolbox. |

The model API exposes only `POST /responses`. Request validation restricts
`model` to the reviewed deployment and rejects `store:true` and
`background:true`; this is the existing foreground, non-stored runtime path.
There are no model-discovery, agent-control, response retrieval or wildcard
operations. Runtime model provenance is **not** rewritten to claim a different
version because a request traversed APIM.

`llm-token-limit` supports Responses: TPM breaches return **429**; daily quota
breaches return **403**. Counts are per gateway, not a global Azure billing cap.
Non-streamed requests use returned usage; streamed requests use estimates.
Concurrent requests can overshoot before accounting completes. This is usage
containment, not a precise prepaid spending limit.

The tools API forwards `POST`, `GET` and `DELETE /mcp` for initialization,
calls, streaming/reconnection and session termination. It preserves the
`Mcp-Session-Id`, `MCP-Protocol-Version`, `Last-Event-ID`, `Accept` and
authorization headers, status codes and SSE content. It fixes `api-version=v1`.
The rate limit counts **HTTP requests**, including discovery, lifecycle and
reconnection requests, not just logical `tools/call` operations. The runtime's
existing read-only allowlist and source guard remain authoritative.

Both policies forward without response buffering, retries, cache lookup/store,
fallback or body rewriting. They deliberately omit policy `<base/>` inheritance
to avoid accidentally inheriting body logging, replay or backend-auth replacement.
An operator must review this against organization-wide mandatory policies before
use; do not deploy if that isolation conflicts with organizational requirements.
This module is an explicit REST pass-through of the existing Toolbox transport,
not a claim that APIM's native MCP catalog/OAuth registration supports this
specific Foundry Toolbox identity flow. Native MCP exposure is a separate option
with its own protocol and authorization prerequisites.

## What still protects the application

Exact commit/source versions, source URI allowlists, evidence checks, model/
prompt/policy/evaluator pins and captured execution records remain in their
existing layers. APIM does not refresh evidence or certify candidate execution.
The shared ADO gateway is not made read-only by this change.

Approved writes still use the existing direct, exact-call approval runtime:
owner/session binding, expiry, replacement-text invalidation, execution state
and unknown-outcome handling remain unchanged. No APIM retry or content
transformation is placed around approved writes. Existing wiki ETag/conditional-
write limitations are unchanged; a gateway does not solve optimistic concurrency.
The push assessment can opt in while its Teams review and write remain direct.

This is **not bypass-proof enforcement**: the identity retains direct backend
access. Network isolation and a separate backend identity would be a separately
reviewed architecture change, not something to enable quietly in this module.

## Observability and privacy

Every deployed API diagnostic sets request/response body bytes to **zero**, logs no headers and
sets `logClientIp=false`. Do not log prompts, source text, tool arguments,
replacement text, tokens or authorization headers. Audit existing **global,
Azure Monitor and logger** settings too: per-API settings
do not prove that every other diagnostic sink is body-free. Review retention
and access before enabling traffic. No diagnostic settings or log export are
changed by this PR on Azure.

### Initial path: built-in Azure Monitor to existing Log Analytics

The [official Azure Monitor tutorial](https://learn.microsoft.com/azure/api-management/api-management-howto-use-azure-monitor)
supports Developer resource logs, resource-specific `ApiManagementGatewayLogs`,
and individual API diagnostic overrides. The
[official API-scope PowerShell example](https://learn.microsoft.com/powershell/module/az.apimanagement/new-azapimanagementdiagnostic?view=azps-16.4.0#example-2-create-a-diagnostic-at-api-scope)
uses an existing **`azuremonitor`** logger and diagnostic ID. A fresh instance
may not have it, so setup explicitly creates the supported `azureMonitor` logger
before global diagnostics, as described above. Our templates
explicitly set **zero** body bytes and **empty** header lists, rather than copying
that example's payload logging. The resource setting selects only `GatewayLogs`
and `logAnalyticsDestinationType=Dedicated` for **`log-foundry-agentic`**.
No category group, metrics export, `GatewayLlmLogs`, prompt/completion logging,
new identity role or App Insights authentication change is requested.

Global and API-scoped **Azure Monitor** diagnostics use `verbosity=information`
and fixed **100% sampling** so successful requests are included, not just errors.
Microsoft's [diagnostic settings reference, preserved in its official source](https://github.com/MicrosoftDocs/azure-docs/blob/917ab49269056f24b3859f21af962276411037a5/articles/api-management/diagnostic-logs-reference.md)
explicitly defines **Error** as failed requests and error traces, and
**Information** as failed **and successful** requests plus information/error traces.
The current Learn reference redirects to REST, whose trace-only wording does
not explain this request-filtering behavior. Do not use `error` as a privacy
control: privacy is enforced separately by zero body bytes, empty header lists,
`logClientIp=false`, no trace policies and GatewayLogs-only export.
Existing Application Insights diagnostic verbosity remains unchanged.

If a previously deployed gateway has error records but no successful records,
read back verbosity at **both** scopes: an API override supersedes global settings.
After source review and fresh validation, redeploy the monitor and model
configuration templates with their existing reviewed parameters; do not recreate
the service, change callers/limits or enable runtime routing. Confirm both Azure
Monitor scopes read back `information` with the same privacy settings, then use
only a separately authorized bounded success probe to verify real ingestion and
privacy. Missing historical success records are not backfilled by this change.
Do not repeat already-proven token-limit probes or treat error-only ingestion
as complete observability acceptance.

Verify the built-in logger and supported diagnostic settings on the actual
service before traffic. Operational logs still include request/service metadata
such as URLs, timing, status and error information; restrict workspace access and
retention and inspect live privacy behavior. Never put source text or credentials
in URLs. The default global settings are deliberately body/header-free too;
review all existing diagnostics before applying them to a reused instance.
Changing `diagnosticType` in incremental deployments does not delete a former
diagnostic sink. Inventory existing sinks rather than assuming only one remains.

### Optional alternative: managed-identity Application Insights

The separate [`managed-insights-logger.bicep`](../infra/ai-gateway/managed-insights-logger.bicep)
references **`appi-foundry-agentic`**, already backed by
**`log-foundry-agentic`** with local authentication disabled. The supported
[APIM managed-identity logger contract](https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights#logger-with-connection-string-and-managed-identity-credentials-recommended)
uses `credentials.identityClientId=SystemAssigned` **plus** the existing
Insights connection string read by ARM. This is keyless **authentication**, not
connection-string-free configuration: routing metadata still contains an
instrumentation identifier. Do not print, commit or output that value or switch
to the portal's instrumentation-key-only setup. No `listKeys` call or local-auth
enablement is used. Only the APIM identity's telemetry publisher role is proposed
at that Insights component; its workspace, retention, local-auth setting and
the project's existing managed-identity ingestion are not changed. This grant
must be separately approved before deployment. APIM receives
no backend model/tool role. Allow telemetry RBAC propagation and verify ingestion;
if it fails, stop rather than silently disabling diagnostics or using key auth.

`X-Gateway-Request-Id` is generated by APIM, not trusted from the caller.
[`requests.kql`](../infra/ai-gateway/requests.kql) is a body-free route-count
query for separately approved resource-specific gateway logs. It is not a
per-agent/version cost ledger; replace its `GatewayResourceId` placeholder with
the exact APIM resource ID before running it in the existing workspace.
Token observations (including `X-Gateway-Tokens`
when available), identity and native run correlation need independent validation
and reconciliation against billing. User-supplied agent/version headers must
never become authorization, budget or chargeback authority.

## Before any live deployment

1. P3 reviews capacity, quotas, logging/retention and the APIM price estimate;
   P2 reviews identity, network, policy inheritance and backend access. Reuse an
   eligible existing instance where appropriate. Foundry's native AI gateway
   association is another option, but enabling a project changes live routing
   and is **not** performed by this module.
2. Review region/tier availability and current pricing. Current Foundry portal
   integration supports existing v2 instances in the same subscription/tenant;
   Standard v2 / Premium v2 network features and prices differ from Basic v2.
   Do not assume a free offer or Developer SLA. The independent bootstrap
   creates a paid service; log ingestion/retention and model usage also incur cost.
3. Review concrete backend URLs, toolbox version/allowlist, caller ID and
   deployment/version mapping against an immutable candidate and this module's
   exact commit. The public Developer service has recorded user authorization;
   an optional new Application Insights telemetry grant still needs explicit
   permission (not needed by the initial Azure Monitor path). Keep publishing and
   live/model calls within their separately authorized scope. The coordinator
   owns Azure validation/deployment; do not change serving selectors or the
   Teams application as part of gateway setup.
4. In an approved isolated candidate, establish a direct baseline; then verify
   the model route with APIM request evidence, denied identities, wrong model,
   required `store:false`, rejected background requests, quota/TPM behavior,
   normal JSON/streaming and explicit errors. Future tool routing requires
   its own MCP initialize/discovery/read/session-cleanup validation. Confirm
   source/provenance equality and the existing push/Teams approval behavior.
   Test 429 and 403 separately; never replay approved writes as a limit test.
5. Roll back by removing the runtime opt-ins and/or CLI ingress flag from the separately reviewed configuration,
   or selecting the known-good direct candidate using the existing release
   safeguards. Do not fall back automatically on a gateway outage. Disabling
   routes/project association does **not** stop APIM or logging charges; resource
   retirement is a separate approved operation after checking other users.

## Local evidence and remaining limits

Local tests exercise the actual pinned Foundry/OpenAI SDK with an in-memory HTTP
transport: direct/opt-in URL selection, renewable token scope, unchanged model/
payload, JSON and SSE handling, and a surfaced 429 with no automatic retry.
The real Toolbox/MCP client is also exercised offline for initialization,
discovery, a read call and session termination, preserving the bearer audience,
session ID and protocol-version headers.
The real synchronous Foundry/OpenAI SDK exercises direct and gateway named-agent
Responses requests, keeping session POST/GET direct, renewable bearer and feature
headers unchanged, result/provenance checks intact and gateway 429s non-retrying.
Production-adapter tests cover both model call sites and read-toolbox selection;
existing guard/approval/push tests remain in place. XML contract checks and
Bicep compilation are local checks, **not APIM policy execution**.
`tests/infra/test_ai_gateway_templates.py` additionally compiles the templates
with `BICEP_CLI` (or `bicep` on PATH), checking conditional tool resources/config/
outputs, explicit limits, model diagnostic dependencies, model-only/legacy
parameter shapes, public single-unit service-only bootstrap,
existing-workspace GatewayLogs-only Azure Monitor settings without roles or
payload categories, explicit credential-free logger creation/dependency and
global default-deny with the existing authenticated model-policy override,
plus the alternative Insights logger's scoped telemetry role.

No Azure provisioning, ARM validation, paid model call, policy enforcement,
runtime Toolbox/APIM compatibility, live streaming/session or cost attribution
has been certified. The artifact is ready for code review and an operator's
separately approved deployment validation, not a claim that all models, tools
and agents are already centrally governed.

## Official references

- [Foundry AI gateway setup, eligibility, verification and disable/delete](https://learn.microsoft.com/azure/foundry/configuration/enable-ai-api-management-gateway-portal)
- [APIM LLM token-limit policy: Responses support and counting limitations](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy)
- [Expose an existing MCP server: protocol/auth limitations and streaming precautions](https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server)
- [AI gateway capabilities](https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities)
- [API Management pricing](https://azure.microsoft.com/pricing/details/api-management/)
- [APIM Application Insights managed-identity integration](https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights)
- [APIM Azure Monitor logging and per-API overrides](https://learn.microsoft.com/azure/api-management/api-management-howto-use-azure-monitor)
