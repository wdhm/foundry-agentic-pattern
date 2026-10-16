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

The user has now accepted transitioning the existing single-identity gateway to
the hosted agent, including interruption of prompt-agent ADO access. The exact
configuration-only plan/context are approved, with an accepted access gap until
hosted deployment. The user has also authorized immediate cutover timing.
An authorized administrator execution context is still required; stop on
conflicting live writers. No duplicate gateway or multi-identity implementation
is proposed. Do not downgrade to a stub.

## Reuse the prompt agent's tools

**Read-only follow-up, 2026-10-16:** reusing the existing backends and project
connections is the preferred preparation path. An empty toolbox does not mean
the tools must be rebuilt or that a second gateway is necessarily required.

| Existing backend / connection | Smallest hosted integration |
|-------------------------------|-----------------------------|
| Foundry IQ / `kb-doc-agent-mcp` | Reference the existing connection in a toolbox as `knowledge`, allowing only `knowledge_base_retrieve`. Preserve project-managed-identity auth and existing Search Index Data Reader grant. No hosted Search grant is established as necessary. |
| GitHub MCP / `github-mcp` | Reference the existing CustomKeys connection as `github`, allowing only `get_file_contents`. Keep the readonly endpoint and credentials on the connection; do not retrieve or copy the PAT into the container. |
| ADO / `ado-mcp-proxy` | Reuse the same Microsoft remote MCP backend/data and transition the existing gateway to the hosted agent's own identity/user. A role assignment alone is insufficient; federation, user consent and all three identity-chain settings must agree. Configuration-only cutover, immediate timing and prompt ADO interruption are approved; authorized admin execution remains outstanding. |

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

### Proposed existing-gateway transition

**Configuration-only plan approved; execution held.** Fresh read-only checks still
show the prompt identity chain, empty toolbox inventory and missing hosted
user/grants/federation. The plan is now configuration-only, not agent deployment.
The proposed operations, in dependency order, are:

| Owner | Proposed change requiring review |
|-------|----------------------------------|
| Entra administrator | Create one agent user linked only to the existing hosted identity. Preserve the prompt user and existing blueprint/runtime credentials. |
| ADO owner | Add that user as **Stakeholder + project Readers** in `integration-team`, with effective project/work-item/wiki reads and no contribution permissions. |
| Entra administrator | Grant only that user Principal-scoped `Ado.Mcp.Tools wit.read wiki.read` consent to the existing ADO MCP application. No `AllPrincipals` or `wiki.write`. |
| Hosted blueprint owner | Trust the existing gateway managed identity through one additional federated identity credential; preserve the existing runtime credential. |
| Gateway app owner | Add an Application role `Mcp.Tools.Read.All` to the existing gateway app and assign it only to the hosted identity. Preserve the existing prompt role/assignment. This is proposed app configuration, not a new app or permission already granted. |
| Coordinated deployment writer | In one existing Container App revision, set the hosted `AGENT_BLUEPRINT_CLIENT_ID`, `AGENT_IDENTITY_CLIENT_ID`, `AGENT_USER_UPN`, plus `MCP_REQUIRED_ROLE=Mcp.Tools.Read.All` and `ADO_MCP_READONLY=true`. Preserve `wit,wiki`, image, managed identity, audience, ingress and scaling. |
| Coordinated deployment writer | Create one versioned `documentation-agent-readonly` toolbox referencing the three existing connections, labels `knowledge`, `github`, `ado`, and only P1's four tool names. Record the returned immutable version-specific endpoint. |

The wiki is verified as a **provisioned project wiki**, not a code wiki.
[Current wiki permissions](https://learn.microsoft.com/azure/devops/project/wiki/manage-readme-wiki-permissions#stakeholder-access-and-wikis)
allow Stakeholder reads of this wiki type even in a private project; a new Basic
license is not assumed necessary. P2 must verify effective ACLs and area access.
Stop on denied reads rather than upgrading licenses, overriding denies or adding
Contributors. Do not run the unmodified onboarding script, whose defaults include
Basic, Contributors, a write scope and the read/write gateway role.

The gateway change deliberately stops prompt ADO access. Preserve prompt IQ,
GitHub and serving configuration. It adds no gateway, model capacity, Foundry
agent or ARM compute resource; existing compute/startup, retrieval and telemetry
can still incur usage charges. No paid invocation has occurred.

Before writes, an authorized Entra operator is required. Read-only checks found
no active directory-admin role for the current operator, and its CLI Graph token
includes `Directory.AccessAsUser.All`; Agent ID guidance requires a supported
explicit-scope Graph credential for these mutations. Do not treat Azure access
or a plan approval as Entra admin authority, initiate login or create an auth app
as a workaround. The user has separately approved the official first-party
Microsoft Graph PowerShell enterprise application and exactly the five operator
scopes below; no custom app or runtime admin grants are included. ADO
membership-management authority also needs confirmation.

#### Supported administrator sign-in

The deployment owner installed official portable PowerShell 7.6.7 in user scope,
verified its release checksum and valid Microsoft executable signature, and
installed `Microsoft.Graph.Authentication` 2.41.2 from PSGallery in CurrentUser
scope. No elevation, global shell replacement or TLS bypass was used.

The human operator needs active **Agent ID Administrator** for linked agent-user
creation and appropriate existing-application authority, normally **Cloud
Application Administrator** or **Application Administrator**, for gateway app
configuration and delegated grants. PIM-eligible roles must be activated first.
ADO entitlement management needs an existing organization owner or Project
Collection Administrator; project/wiki/area ACL changes need the corresponding
Manage permissions authority. These are operator roles, never agent permissions.

Use an explicit tenant and the approved official Graph PowerShell client:

```powershell
$scopes = @(
    'User.Read'
    'AgentIdUser.ReadWrite.All'
    'Application.ReadWrite.All'
    'AppRoleAssignment.ReadWrite.All'
    'DelegatedPermissionGrant.ReadWrite.All'
)
Connect-MgGraph -TenantId '<approved-tenant-id>' `
    -ClientId '14d82eec-204b-4c2f-b7e8-296a70dab67e' `
    -Scopes $scopes -ContextScope Process -UseDeviceAuthentication
Get-MgContext | Select-Object TenantId,ClientId,AuthType,ContextScope,Scopes
```

The [supported device flow](https://learn.microsoft.com/powershell/microsoftgraph/authentication-commands#delegated-access)
avoids a hidden WAM sign-in window in an embedded terminal. Complete the login
only through the official Microsoft address displayed in that terminal. Do not
paste device codes, tokens or credentials into chat. Confirm the actual returned
Graph context, required scopes and successful target GETs; a browser success page
alone is insufficient. Read success is not proof of administrative authority.
Do not request `.default`, `Directory.AccessAsUser.All`, create-blueprint/
create-identity scopes or extra consent automatically.

Keep that same process open for later reviewed `Invoke-MgGraphRequest` operations.
`-ContextScope Process` does not authenticate a fresh shell or WSL Azure CLI.
The ignored bootstrap writes nonsecret context/target IDs locally, never tokens,
and performs no migration writes. If a required permission is denied, stop with
the exact operation/role rather than broadening scopes or copying credentials.

Use the authorized immediate cutover window, stop on conflicting live writers
and take a fresh nonsecret before snapshot. For reviewed rollback, restore the original three prompt identity
settings and remove the two newly introduced role/read-only overrides, which
were previously absent; retain the original image and unrelated settings.
Preserving prompt grants and federation keeps that restoration possible.
No automatic rollback, agent serving PATCH or deletion of added objects is
included; cleanup needs separate dependency review and approval.

Remaining verification: actual toolbox `tools/list` must return P1's four
`server_label___tool_name` names with compatible arguments/results. P1 expects Git
`documents[].content`, wiki `page` plus `eTag`, and work-item `fields` plus `rev`;
connection reuse alone does not prove those shapes. The alignment owner confirmed
there is no captured live schema evidence: passing offline doubles are not
backend compatibility proof. Actual service/installed-SDK names are authoritative
if documentation differs. Stop for P1/P2 on mismatches; no custom adapter or
broader allowlist is included. Hosted model/toolbox access must be verified
before deciding whether an additional project role is needed.

**Verification boundary:** deployed hosted version 2 is a stub and never calls
the toolbox. Configuration existence and gateway health cannot prove actual
hosted reads. Agentic identity also requires a genuine agent request context;
standalone human `tools/list` is not hosted proof. Do not spoof context or use
prompt/gateway credentials. A functional assessment version, serving isolation,
build and one bounded assessment invocation require separate approval.
Until then report **configured, awaiting hosted runtime proof** only after actual
configuration changes, not deployment success. The user has explicitly accepted
configuration-only cutover and the resulting ADO access gap until hosted
deployment; that decision does not authorize a hosted version, serving change or
billable invocation. Cutover still awaits supported authorized admin execution.

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
