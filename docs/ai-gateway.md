# Optional AI gateway: governance without replacing the agent

An Azure API Management (APIM) AI gateway is a good **additional** platform
boundary: it can authenticate callers, constrain model selection and usage, and
throttle access to a versioned toolbox. It cannot determine whether an answer is
supported by sources or whether a human approved the exact write.

**Repository integration only; nothing deployed or rerouted.** This opt-in
increment reopens the earlier slides-only disposition in ADR 0022 for review.
It does not turn the workshop into a production platform. See
[ADR 0027](adr/0027-opt-in-ai-gateway.md).

## Three different traffic paths

| Path | Opt-in integration | What it does not cover |
|---|---|---|
| Hosted assessment -> model | `DOCUMENTATION_MODEL_GATEWAY_ENDPOINT` routes the existing Foundry client's OpenAI **Responses model-inference API** through APIM. Applies to assessment, live-source evaluation, supplied-source evaluation, and the assessor in the push-to-Teams flow. | Foundry service-side built-in evaluator calls, old prompt agents, other applications, and traffic that retains direct configuration. |
| Hosted assessment -> Foundry Toolbox -> existing ADO gateway / GitHub / knowledge | `DOCUMENTATION_TOOLBOX_GATEWAY_ENDPOINT` routes read-toolbox MCP transport through APIM. Exact backend toolbox version is set in the infrastructure, not selected by callers. | APIM does not replace the toolbox, parse per-tool permissions, exchange delegated ADO identity, or become a new ADO gateway. Write-toolbox calls stay direct. |
| Client / pipeline / Teams -> Foundry hosted agent | **Unchanged.** Foundry continues to host Responses and Activity. Session binding, selectors, Teams authentication and push inbox state are unchanged. | No new APIM agent-ingress endpoint, Invocations application, Teams callback proxy or fleet-wide agent governance is claimed. |

The first row's `/responses` is **model inference**, not the third row's
version-bound hosted-agent session API. Pointing a project or agent endpoint at
a generic proxy would conflate these paths and their identity/session semantics.

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

[`infra/ai-gateway/main.bicep`](../infra/ai-gateway/main.bicep) configures two
APIs on an **existing, separately approved APIM instance**, plus named values,
policies and body-free Application Insights diagnostics using an existing logger.
It does not create an APIM service, logger, Foundry resource, identity or RBAC
assignment; it is not wired into CI or the existing release/deployment scripts.

| Configuration | Review requirement |
|---|---|
| `apimName`, `loggerResourceId` | Existing instance and its APIM Application Insights logger resource ID. Fixed API/named-value names mean one reviewed project/caller per instance for this module; do not overwrite another installation. |
| `projectEndpoint` | Exact HTTPS Foundry project endpoint, no trailing slash; must equal the candidate's `DOCUMENTATION_PROJECT_ENDPOINT`. |
| `readToolboxBaseUrl` | Exact HTTPS versioned **read-only** Foundry Toolbox URL ending `/toolboxes/<name>/versions/<number>`, no `/mcp`, query or trailing slash. Must correspond to the candidate's direct `TOOLBOX_ENDPOINT`. Never target the write toolbox or the ADO gateway directly. |
| `tenantId`, `callerObjectId` | Reviewed tenant and calling managed identity's **object** ID, not its client ID or a caller-supplied agent-name header. |
| `modelDeployment` | Same deployment as `AZURE_AI_MODEL_DEPLOYMENT_NAME`; preserve/review its concrete `DOCUMENTATION_MODEL_VERSION` and evaluator pins independently. |
| `tokensPerMinute`, `dailyTokenQuota`, `toolRequestsPerMinute` | Required positive values; no production budget or capacity is chosen by default. Token counters aggregate this route's project/deployment; tool counters aggregate the configured toolbox. |

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

API diagnostics set request/response body bytes to **zero**, log no headers and
disable client-IP logging. Do not log prompts, source text, tool arguments,
replacement text, tokens or authorization headers. Audit existing **global,
Azure Monitor and logger** settings too: per-API Application Insights settings
do not prove that every other diagnostic sink is body-free. Review retention
and access before enabling traffic. No diagnostic settings or log export are
changed by this PR on Azure.

`X-Gateway-Request-Id` is generated by APIM, not trusted from the caller.
[`requests.kql`](../infra/ai-gateway/requests.kql) is a body-free route-count
query for separately approved resource-specific gateway logs. It is not a
per-agent/version cost ledger. Token observations (including `X-Gateway-Tokens`
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
   Do not assume a free offer, Developer SLA or zero cost because this PR creates
   no service. APIM, log ingestion/retention, and model usage can all incur cost.
3. Review concrete backend URLs, toolbox version/allowlist, caller ID and
   deployment/version mapping against an immutable candidate and this module's
   exact commit. Obtain separate approval before ARM deployment/validation,
   identity grants, publishing or any live/model calls. Do not change serving
   selectors or the Teams application as part of gateway setup.
4. In an approved isolated candidate, establish a direct baseline; then verify
   both gateway routes independently with APIM request evidence, denied
   identities, wrong model, quota/TPM behavior, normal JSON and streaming,
   MCP initialize/discovery/read/session cleanup and explicit errors. Confirm
   source/provenance equality and the existing push/Teams approval behavior.
   Test 429 and 403 separately; never replay approved writes as a limit test.
5. Roll back by removing the two opt-ins from a separately reviewed deployment,
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
Production-adapter tests cover both model call sites and read-toolbox selection;
existing guard/approval/push tests remain in place. XML contract checks and
Bicep compilation are local checks, **not APIM policy execution**.

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
