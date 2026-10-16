# Hosted assessment deployment: preparation and gates

**Status, 2026-10-16: blocked before deployment.** This prepares the committed
P1 hosted runtime under [ADR 0024](../adr/0024-hosted-documentation-runtime.md).
It does not complete hosted source integration, approval enforcement, release
certification or Teams publication. No Azure mutations or remote invocations
were performed. The canonical, environment-specific plan is the deployment
owner's ignored `.azure/deployment-plan.md`; this guide contains no tenant IDs.

## Verified state and blockers

| Surface | Read-only result |
|---------|------------------|
| Source | Current main `1ddaec87a8cb5e50af38d817c44642378bc8f63f` |
| Hosted agent | `documentation-agent`, versions 1 and 2 active, latest 2 |
| Retained baseline | Version 2, historical stub application 0.1.0; not an assessment baseline |
| Retained image | Existing ACR digest recorded in [setup](../setup.md#hosted-contract-stub-p1-7), manifest still readable |
| Prompt reference | `doc-agent:3`, preserved |
| Both named endpoints | `@latest` / 100%, Responses, Entra, `not_published` |
| Toolbox | Successful `GET /toolboxes?api-version=v1` returned an empty list |
| Source connections | GitHub CustomKeys, IQ ProjectManagedIdentity, ADO AgenticIdentityToken; not themselves a toolbox |
| ADO gateway | Identity and blueprint still match the prompt agent, not hosted |
| Models | Existing `gpt-6-luna` revision `2026-09-22` and embedding retained |

Use authenticated WSL, not a stale Windows cache. The installed azd toolbox
command returned `WorkspaceNotFound`; that failure alone is not an empty
inventory. The successful `v1` REST GET provides the empty-inventory evidence.
Do not dump connection metadata, credentials or `azd env get-values` into logs.

Hosted model/session permissions can be supplied by platform defaults; an empty
Azure role listing is not proof of access denial. Conversely, connection presence
and a prompt-agent success do not prove hosted toolbox/source authentication.
Verify the actual hosted credential and each allowed read, without automatically
granting broader roles.

## Minimum P1/P2 integration

P2 must supply a versioned toolbox exposing exactly:

- `knowledge___knowledge_base_retrieve`
- `github___get_file_contents`
- `ado___wiki`
- `ado___wit_work_item`

P2 owns connection authentication, source access and hosted-compatible ADO
authorization. P1 owns compatibility of the real tool schemas/results with
the committed read guard and evidence parser. Standard retrieval is mandatory.
Git reads must use the requested repository and commit; ADO reads must remain
within the configured project/wiki and requested paths/work-item IDs.

Creating a toolbox is additional data-plane configuration, not an existing
resource discovered by this preparation. Verify whether existing IQ/GitHub
connections can be reused without changing the prompt agent. The current gateway
serves a single agent identity; running onboarding re-points it. Do not run
onboarding as an incidental deployment step.

If hosted ADO access cannot reuse the current configuration safely, P2 must
propose a reviewed extension of the existing gateway, a separately scoped gateway,
or an explicitly coordinated identity transition. That proposal needs its own
code/configuration, cost, consent, entitlement and permission review.
**Neither shared gateway changes, new infrastructure nor gateway repointing is
approved here.** The deployment owner must wait rather than downgrade to a stub.

## Reuse the prompt agent's tools

**Read-only follow-up, 2026-10-16:** reusing the existing backends and project
connections is the preferred preparation path. An empty toolbox does not mean
the tools must be rebuilt or that a second gateway is necessarily required.

| Existing backend / connection | Smallest hosted integration |
|-------------------------------|-----------------------------|
| Foundry IQ / `kb-doc-agent-mcp` | Reference the existing connection in a toolbox as `knowledge`, allowing only `knowledge_base_retrieve`. Preserve project-managed-identity auth and existing Search Index Data Reader grant. No hosted Search grant is established as necessary. |
| GitHub MCP / `github-mcp` | Reference the existing CustomKeys connection as `github`, allowing only `get_file_contents`. Keep the readonly endpoint and credentials on the connection; do not retrieve or copy the PAT into the container. |
| ADO / `ado-mcp-proxy` | Reuse the same Microsoft remote MCP backend/data. The current gateway cannot accept the hosted identity unchanged, even if an app role is granted; it requires a reviewed gateway extension or separately approved alternative. |

Foundry officially supports [toolbox entries referencing existing project
connections](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox#create-a-toolbox-version).
[Authentication remains on those connections](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-authentication),
separate from the hosted identity's access to the toolbox itself. P1 already
uses the [supported `FoundryToolbox` integration](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent),
including request call-ID propagation. Do not copy the prompt agent's identity or
forward the assessment to the prompt agent as a workaround.

### Exact ADO constraint

The live gateway still uses image `ado-mcp:0.2.1`, the prompt identity/blueprint,
and one configured identity chain. Source inspection shows two independent
constraints:

- [`TokenValidator.validate`](../../src/tools/ado_mcp/ado_mcp/inbound_auth.py)
  rejects any validated token whose `azp`/`appid` differs from the single configured
  caller. `server.py` binds that caller to `AGENT_IDENTITY_CLIENT_ID`.
- [`AgentUserTokenProvider`](../../src/tools/ado_mcp/ado_mcp/agent_user_token.py)
  always exchanges the configured blueprint/identity/agent-user chain and caches
  one downstream token. Simply accepting another caller would still use the
  prompt agent's user, breaking attribution and isolation.

Narrow Graph reads found no user linked to the hosted identity, no hosted
delegated grants, no hosted gateway app-role assignment, and no federation of
the existing gateway managed identity on the hosted blueprint. The gateway app
currently exposes only `Mcp.Tools.ReadWrite.All`. These are authorization/configuration
gaps, not evidence that another compute resource is mandatory.

The [agent-user protocol](https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow)
binds an agent user to one agent identity. Sharing the prompt agent's user or
swapping its client ID is not a supported shortcut. Direct MCP wiring also does
not remove the gateway's checks or Azure DevOps' need for the agent-user flow.

### Smallest next P1/P2 decision

The user prefers coordination with P1/P2 over duplicate infrastructure or custom
compatibility work. **No gateway implementation is included in this preparation.**

P2 should decide whether to transition the existing gateway from the prompt agent
to the hosted agent. This reuses the existing service and ADO connection, but
requires the hosted agent's own linked agent user, read-only ADO membership and
delegated consent, gateway app-role authorization and blueprint federation.
The gateway's three `AGENT_*` settings then identify that hosted chain.
**That change would stop the old prompt agent's ADO access**; it is not a
transparent permission addition and requires explicit P1/P2 coordination.

P2 must review appropriate ADO access level/cost, scopes
`Ado.Mcp.Tools wit.read wiki.read`, read-only upstream filtering and a suitable
gateway role. The only current gateway role is read/write; do not silently grant
it or run the unmodified onboarding script, which grants Contributors/write scope
and re-points the gateway unless skipped.

If both agents must retain ADO access simultaneously, the current gateway cannot
provide it by configuration alone. P2 must separately own and review a multi-identity
gateway change or alternative, including caller/token-cache/MCP-session isolation.
A new gateway is not automatically required, and none is proposed for execution.

Once P2 resolves that decision, one versioned toolbox can reference the existing
three connections with labels `knowledge`, `github`, `ado`, exposing only the four
P1 read tools. P1 supplies the assessment configuration and retains its action,
repository/SHA/project/wiki guards. No new Foundry agent, backend data, Search
service or copied credentials are needed for this reuse plan.

Remaining verification: actual toolbox `tools/list` must return P1's four
`server_label___tool_name` names with compatible arguments/results. P1 expects Git
`documents[].content`, wiki `page` plus `eTag`, and work-item `fields` plus `rev`;
connection reuse alone does not prove those shapes. Hosted model/toolbox access
must be verified before deciding whether an additional project role is needed.
Before a live rollout, require offline tests for unknown callers, token-cache and
MCP-session isolation, hosted write rejection and unchanged prompt behavior.
Later, separately approved read-only integration must verify correct downstream
identity and source evidence. No paid invocation was performed for this analysis.

## Container preparation

Build from the repository root, using the existing Dockerfile and explicit
`linux/amd64`. All three packages declared by `pyproject.toml` must be copied and
allowed by `.dockerignore`: `contracts`, `documentation_agent`, and `tools`.
The last package is required for wheel construction even though the hosted entry
point does not call the trigger CLI. Assessment prompt/policy files are package
data and must be present in the installed wheel.

The omitted `src/tools` failure was reproduced with the Docker COPY inputs.
The corrected inputs successfully built a wheel containing all packages and
assessment prompt/policy. A full local image build failed earlier in pip TLS
negotiation with the public package host. No credential-free mirror was configured.
A successful wheel build is **not** a successful image build or hosted smoke.
Resolve trusted package access locally; never disable TLS verification, pass
credentials in build arguments, or switch to billable Azure builds without approval.

Keep the existing container method, existing ACR and immutable image digest.
Do not provision another Foundry stack or switch to direct code deployment merely
because a generic guide recommends it. Keep build/config scratch ignored.

## Candidate configuration

The committed `agent.yaml` intentionally defaults to `DOCUMENTATION_MODE=stub`.
An assessment candidate needs all settings in the
[runtime guide](../../src/agents/documentation-agent/README.md#run-assessment-mode-after-p2-supplies-access):
assessment mode, managed identity, existing project endpoint, actual toolbox MCP
endpoint, existing chat deployment and its actual revision, exact ADO project/wiki,
`HOST=0.0.0.0`, and port 8088. Missing settings must fail, not fall back.

The stable Projects SDK uses `container_configuration.image` and
`protocol_versions` for hosted definitions; the legacy flat `agent.yaml` template
is not a serialized stable-SDK payload. Verify the exact installed SDK/azd schema
and resulting environment before creating a version.

## Required approval and serving isolation

The creator must obtain exact subscription/location and bounded plan approval,
plus a real hold covering P1/P2, portal writers, CI and deployment hooks. No
coordination or approval is inferred from silence. Prior approval to pin prompt
version 3 does not authorize any hosted selector change.

Before candidate creation, explicitly review retained hosted version `G` (version
2 is the current historical stub candidate), refresh its active state/image and
preserve identity, protocols, authorization and complete endpoint configuration.
With explicit hosted approval, pin `G` at 100%, read back unchanged configuration
and verify a fresh named-serving session if that probe is approved. There is no
verified atomic `If-Match` contract; stop on unexpected state or a missing hold.
See the [serving runbook](release-rollback-guide.md#candidate-isolation-and-release-sequence).

**Inspect deployment hooks before using azd.** `azd ai agent endpoint update`
PATCHes manifest `agentEndpoint`/`agentCard`. Public azd source also performs
post-deploy endpoint patches when those fields are supplied:
[Deploy / patchAgentEndpointFields](https://github.com/Azure/azure-dev/blob/1bd2ca4699c7b1f371db85dd867f18aa4fbc4730/cli/azd/extensions/azure.ai.agents/internal/project/service_target_agent.go).
This source review does not establish the installed `agents1.0.0-beta.18`
binary's exact behavior. Confirm the chosen version, resolved service/reference
and all hooks preserve `G` before deploy; do not trust generic deploy success.
No executable deployment configuration was generated during preparation.

After integration, image and isolation gates clear, complete `azure-prepare`,
set the local plan to `Ready for Validation`, invoke `azure-validate` and capture
actual proof. Only then invoke `azure-deploy` for the approved immutable image and
one candidate. Never manually claim `Validated`. Preserve previous images and
versions; no automatic delete, rollback, promotion, traffic split or publication.

## Cost and capacity boundary

The proposed deployment reuses Foundry, ACR, chat/embedding, Search, gateway and
native `appi-foundry-agentic` / `log-foundry-agentic`; it includes no ARM
provisioning, new model capacity or evaluator deployment. No Azure-side build,
eval suite, write-tool execution or Teams/Bot is included.

Future candidate storage, hosted CPU/memory while active (including session idle),
one model-backed smoke, source retrieval and telemetry can incur charges. The
existing 0.5-vCPU/1-GiB size is a supported tier, not verified spare capacity.
A separately approved named-serving baseline probe also consumes hosted compute.
Any additional isolated gateway requires separate cost/resource approval.

The quota CLI returned `BadRequest` for CognitiveServices. Provider-specific
regional usages did not report hosted compute quota; existing chat allocation
also exceeded the returned regional limit. No quota/capacity change was made.
Do not report capacity validation as passed or alter the working model to repair
that pre-existing discrepancy.

## Meaningful smoke and evidence

After approval, submit exactly one user text containing a bare `AgentRequest` v1,
using the pinned fictional integration in
[`examples/assessment-request.json`](../../src/agents/documentation-agent/examples/assessment-request.json).
Generate fresh request/correlation IDs locally. It targets the sample at commit
`ad623147fbb1eeb9a6423d437df199c91db15a9e`, wiki `/Order Sync/Overview` and
work-item 1. Verify these sources are accessible without expanding the allowlist.
Do not attach a snapshot envelope or treat `tool_choice=none` as this tool-backed
assessment.

Create a fresh session explicitly bound to returned candidate `C`; require its
`version_indicator` to identify `C`, then invoke Responses using that session ID.
Require active readiness, exact digest/configuration, terminal `completed`,
schema-valid `AgentResult` v1, matching request ID, app provenance **0.2.0**,
actual model revision and prompt/policy hashes. Record the concrete Foundry
version separately from the application version.

Version-specific sessions bypass the named serving selector. Candidate success
is not named-serving, promotion or Teams proof. Re-read serving configuration
and require it still points to `G`. The nested read guard checks evidence, but
outer Responses does not export nested tool calls/schemas needed for release
tool-accuracy certification. Record available hosted traces and missing spans;
prompt traces are not hosted evidence.

Route Foundry's post-deploy evaluation-suite choice to the creator. Do not
generate synthetic data, run a suite or provision a judge without separate
approval. End with the exact artifact/version/session, preserved selector,
limitations, consumption/resource changes and cleanup needs; open a reviewable
PR, not an automatic merge.
