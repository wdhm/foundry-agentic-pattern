# Workshop guide: a Foundry agent that writes to Azure DevOps as itself

This guide explains how the Documentation Agent reads work items and updates the Azure DevOps wiki under **its own identity**. No person's account and no stored secrets are involved. It records what we tried, what failed and why, and the exact setup steps. Each step links to Microsoft Learn.

> Decision: [ADR 0021](../adr/0021-agent-user-and-ado-mcp-gateway.md). Risk: [R3](../risks.md#r3). Environment values: [setup runbook](../setup.md#agent-identity-and-azure-devops). Code: [`src/tools/ado_mcp`](../../src/tools/ado_mcp/README.md).

## The result

```mermaid
sequenceDiagram
    participant U as User / CI
    participant F as Foundry Agent Service<br/>(agent doc-agent-spike)
    participant G as ado-mcp gateway<br/>(Container Apps, user-assigned MI)
    participant E as Microsoft Entra ID
    participant M as Azure DevOps remote MCP server<br/>mcp.dev.azure.com/{org}
    U->>F: "Update /Order Sync/Overview from work item 1"
    F->>G: MCP tools/list, tools/call<br/>Bearer = agent identity token (aud = gateway app)
    G->>G: Validate token: issuer, audience, app role, caller = agent identity
    G->>E: MI token -> T1 blueprint -> T2 agent identity -> T3 agent user (user_fic)
    E-->>G: Token for the agent user (idtyp=user, scp=wit.read wiki.write ...)
    G->>M: Same MCP request, Bearer = agent user token,<br/>X-MCP-Toolsets enforced by the gateway
    M-->>G: Result (SSE)
    G-->>F: Result (streamed through)
    Note over F: wiki_upsert_page pauses for approval<br/>(require_approval: always)
```

What the wiki history shows: the commit author is **`doc-agent-spike (agent user)`**, not a person.

## Concepts in one minute

| Concept | What it is | Learn |
|---|---|---|
| **Agent identity** | A special service principal that Foundry creates for each agent. Foundry uses it to authenticate the agent to tools. | [Agent identity concepts in Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity) |
| **Agent identity blueprint** | The application that agent identities are created from. It holds the credentials (federated credentials) that can request tokens for the agent identities. | [Create an agent identity blueprint](https://learn.microsoft.com/entra/agent-id/create-blueprint) |
| **Agent user** (agent's user account) | A user object linked 1:1 to an agent identity, for systems that only accept users. Its tokens carry `idtyp=user`. | [Create agentUser (Graph)](https://learn.microsoft.com/graph/api/agentuser-post?view=graph-rest-1.0), [Agent user OAuth flow](https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow) |
| **Agent user OAuth flow** | A token exchange: blueprint token (T1), then agent identity token (T2), then a token for the agent user (T3, `grant_type=user_fic`). | [Agent user OAuth flow](https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow) |
| **Remote Azure DevOps MCP server** | An MCP server that Microsoft hosts at `https://mcp.dev.azure.com/{org}`. It is Entra-authenticated, and you can restrict its tools with `X-MCP-*` headers. | [Set up the remote Azure DevOps MCP Server](https://learn.microsoft.com/azure/devops/mcp-server/remote-mcp-server) |
| **Foundry MCP tool + project connection** | The agent calls an MCP server through a project connection. With `AgenticIdentityToken` auth, Foundry sends an agent identity token for the connection's audience. | [MCP tool authentication](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication), [Connect agents to MCP servers](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol) |

## What we tried and learned

| # | Attempt | Result | Learning |
|---|---|---|---|
| 1 | Agent identity → Azure DevOps REST (app-only token) | ❌ Azure DevOps could not resolve the identity | Azure DevOps supports service principals and managed identities, but **not agent identities**. Learn does not document agent identity support for Azure DevOps. |
| 2 | Foundry MCP tool → `mcp.dev.azure.com` directly, connection `AgenticIdentityToken` | ❌ First a 401 (wrong audience); with audience `https://mcp.dev.azure.com`: *"Identity … is currently Deleted"* | Get the audience from `/.well-known/oauth-protected-resource/{org}`. Even with the right audience, Azure DevOps rejects the agent identity's app-only token. |
| 3 | Agent **user** token (user_fic flow) → Azure DevOps REST | ✅ Read work items, wiki commit by "doc-agent-spike (agent user)" | Azure DevOps accepts the agent user like any member user. It needs a license and project permissions. |
| 4 | Agent **user** token → Microsoft's remote Azure DevOps MCP server | ✅ `initialize`, `tools/list`, `wit_work_item`, `wiki_upsert_page` | You get Microsoft's maintained tools; you only add the identity exchange. |
| 5 | Foundry → **our gateway** → Microsoft's MCP server, as the agent user | ✅ End to end, with approval on the write tool | This is the chosen design ([ADR 0021](../adr/0021-agent-user-and-ado-mcp-gateway.md)). |

### Options we compared

| Option | Identity in Azure DevOps | Unattended | Verdict |
|---|---|---|---|
| **A.** Our own MCP server calling the Azure DevOps REST API | Agent user | ✅ | Works, but we would maintain tool code that Microsoft already ships. |
| **B.** Thin gateway in front of Microsoft's remote MCP server (**chosen**) | Agent user | ✅ | Small code (identity exchange + header policy) and Microsoft's tools. |
| **C.** Microsoft's server via Foundry OAuth passthrough (catalog) | **A signed-in person** | ❌ | Ruled out: actions are attributed to a person and need an interactive sign-in. |

**Why a gateway is needed at all:** Foundry can send only the agent identity's token (an app token), and Azure DevOps accepts only the agent user. The user_fic exchange must run somewhere that holds a blueprint credential. Foundry does not do that exchange, so our gateway does.

## Setup, step by step

Placeholders: `<tenant>`, `<blueprint-app-id>`, `<agent-identity-id>`, `<agent-user-upn>`, `<mi-client-id>`, `<gateway-app-id>`. The real values for the shared environment are in the [setup runbook](../setup.md#agent-identity-and-azure-devops).

### 1. Create the Foundry agent (this creates the agent identity)

Create a prompt agent in the Foundry project (portal or `POST {project}/agents/{name}/versions`). Foundry creates the **agent identity blueprint** and the **agent identity**. In Entra, the agent identity appears as `<account>-<project>-<agent>-AgentIdentity`.

- Learn: [Agent identity concepts](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity), [Agent types during the transition](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications#agent-types-during-the-transition)
- **Every new agent gets its own identity and blueprint** when you create it. New versions of the same agent keep that identity: we checked versions v1 → v3. So steps 2–6 are needed **once per agent**, and [`onboard-agent.ps1`](#onboard-another-agent-automated) does them for you.
- Gotcha: older material says publishing creates a new identity. That applies to **legacy** agents and to the legacy *Agent Application* publish flow ([Publish as an Agent Application](https://learn.microsoft.com/azure/foundry/agents/how-to/agent-applications)). Legacy agents (with `instance_identity` set to `null`) use the shared project identity. Check which model your agent uses with `GET {project}/agents/{name}?api-version=2025-11-15-preview` and the header `Foundry-Features: AgentEndpoints=V1Preview`: `instance_identity` and `blueprint` are set for new-model agents.

### 2. Create the agent user

Create the agent user with Microsoft Graph, linked to the agent identity:

```http
POST https://graph.microsoft.com/beta/users
{
  "@odata.type": "microsoft.graph.agentUser",
  "displayName": "doc-agent-spike (agent user)",
  "userPrincipalName": "doc-agent-spike@<tenant-domain>",
  "mailNickname": "doc-agent-spike",
  "accountEnabled": true,
  "identityParentId": "<agent-identity-id>"
}
```

- Learn: [Create agentUser](https://learn.microsoft.com/graph/api/agentuser-post?view=graph-rest-1.0), [New-EntraAgentUserForAgentId](https://learn.microsoft.com/powershell/module/microsoft.entra.users/new-entraagentuserforagentid?view=entra-powershell)
- The agent user has no password. It can only get tokens through the agent identity.

### 3. Give the agent user access in Azure DevOps

1. Add the agent user to the organization (Organization settings → Users), with access level **Basic**. Stakeholder can't edit the wiki.
2. Add it to the project's **Contributors** group, or to a narrower custom group with *work item read* and *wiki contribute*.

- Learn: [Add organization users](https://learn.microsoft.com/azure/devops/organizations/accounts/add-organization-users), [Access levels](https://learn.microsoft.com/azure/devops/organizations/security/access-levels), [Wiki permissions](https://learn.microsoft.com/azure/devops/project/wiki/manage-readme-wiki-permissions)

### 4. Register the Azure DevOps MCP resource in the tenant and grant consent

The remote MCP server's Entra application is **"Azure DevOps MCP"** (appId `2a72489c-aab2-4b65-b93a-a91edccf33b8`). It exposes fine-grained delegated scopes such as `wit.read`, `wiki.read` and `wiki.write`, plus `Ado.Mcp.Tools`.

1. If the tenant has no service principal for it yet, create one:
   ```http
   POST https://graph.microsoft.com/v1.0/servicePrincipals
   { "appId": "2a72489c-aab2-4b65-b93a-a91edccf33b8" }
   ```
2. Grant **delegated consent for the agent user only** (consentType `Principal`), with the agent identity as the client:
   ```http
   POST https://graph.microsoft.com/v1.0/oauth2PermissionGrants
   {
     "clientId": "<agent-identity-id>",
     "consentType": "Principal",
     "principalId": "<agent-user-object-id>",
     "resourceId": "<azure-devops-mcp-sp-object-id>",
     "scope": "Ado.Mcp.Tools wit.read wiki.read wiki.write"
   }
   ```

- Learn: [Create oauth2PermissionGrant](https://learn.microsoft.com/graph/api/oauth2permissiongrant-post?view=graph-rest-1.0), [Agent user OAuth flow](https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow)
- Gotcha: without this grant, T3 fails with **AADSTS65001** (no consent). Grant only the scopes the agent needs.
- Tip: find the resource and scope with `GET https://mcp.dev.azure.com/.well-known/oauth-protected-resource/{org}`.

### 5. Create the gateway's identity: a user-assigned managed identity as a blueprint credential

1. Create a user-assigned managed identity (`id-doc-agent-mcp`).
2. Add a **federated identity credential** on the **blueprint** application that trusts this managed identity (issuer `https://login.microsoftonline.com/<tenant>/v2.0`, subject = MI principal id, audience `api://AzureADTokenExchange`).

- Learn: [Configure credentials for the blueprint](https://learn.microsoft.com/entra/agent-id/create-blueprint#configure-credentials-for-the-agent-identity-blueprint), [Workload identity federation with managed identities](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity)
- Result: the gateway can run the agent user flow **with no secrets**.
- Verified: our extra credential survives new agent versions, next to Foundry's own `fmi-fic` credential. Still open: whether it survives publishing to Microsoft 365 / Teams, which is tested in [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4) ([R3](../risks.md#r3)).

### 6. Protect the gateway with its own Entra app

1. Register an app `doc-agent-mcp-api`. Set its identifier URI to `api://<gateway-app-id>` and add an **app role** `Mcp.Tools.ReadWrite.All` (allowed member type: Applications).
2. Assign the app role to the **agent identity**.
3. The gateway accepts only tokens where:
   - the audience is this app;
   - the role is present;
   - `azp`/`appid` is the agent identity.

- Learn: [Deploy a self-hosted remote MCP server and connect it from Foundry](https://learn.microsoft.com/azure/developer/azure-mcp-server/how-to/deploy-remote-mcp-server-microsoft-foundry) (the same Entra app + app role pattern), [Add app roles](https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps)

### 7. Deploy the gateway

The code is in [`src/tools/ado_mcp`](../../src/tools/ado_mcp/README.md). It is a small ASGI app that:

1. validates the inbound agent identity token;
2. runs MI → T1 → T2 → T3 to get the agent user token, and caches it;
3. forwards `/mcp` to `https://mcp.dev.azure.com/{org}`. Only the MCP transport headers are forwarded, and the gateway sets `X-MCP-Toolsets` itself;
4. logs which MCP method or tool the agent called (no arguments or content).

```powershell
az acr build -r <acr> -t ado-mcp:<version> src/tools/ado_mcp
az containerapp env create -g <rg> -n cae-doc-agent-mcp -l northeurope --logs-destination none
az containerapp create -g <rg> -n ca-doc-agent-mcp --environment cae-doc-agent-mcp `
  --image <acr>.azurecr.io/ado-mcp:<version> --registry-server <acr>.azurecr.io `
  --registry-identity <mi-resource-id> --user-assigned <mi-resource-id> `
  --ingress external --target-port 8000 --min-replicas 1 --max-replicas 1 `
  --env-vars AZURE_TENANT_ID=<tenant> MCP_APP_CLIENT_ID=<gateway-app-id> `
    AGENT_BLUEPRINT_CLIENT_ID=<blueprint-app-id> AGENT_IDENTITY_CLIENT_ID=<agent-identity-id> `
    AGENT_USER_UPN=<agent-user-upn> MANAGED_IDENTITY_CLIENT_ID=<mi-client-id> `
    ADO_ORG=<org> ADO_MCP_TOOLSETS=wit,wiki
```

- Learn: [Container Apps managed identity image pull](https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull), [Managed identities in Container Apps](https://learn.microsoft.com/azure/container-apps/managed-identity)
- Check: `GET /healthz` returns 200, and `POST /mcp` without a token returns 401.

### 8. Connect the gateway to the agent in Foundry

1. Create a **project connection**: category `RemoteTool`, authType `AgenticIdentityToken`, target `https://<gateway-fqdn>/mcp`, audience `api://<gateway-app-id>`.
2. Add an **MCP tool** to the agent version. Use `project_connection_id` = the connection, list `allowed_tools`, and set `require_approval` to `always` for write tools:

```json
{
  "type": "mcp",
  "server_label": "ado",
  "server_url": "https://<gateway-fqdn>/mcp",
  "project_connection_id": "ado-mcp-proxy",
  "allowed_tools": ["wit_work_item", "wit_query", "wiki", "search_wiki", "search_workitem", "wiki_upsert_page"],
  "require_approval": {
    "never":  { "tool_names": ["wit_work_item", "wit_query", "wiki", "search_wiki", "search_workitem"] },
    "always": { "tool_names": ["wiki_upsert_page"] }
  }
}
```

- Learn: [MCP tool authentication (agent identity)](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication#microsoft-entra-authentication), [Connect agents to MCP servers](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol)

### 9. Verify end to end

1. **Read:** call `POST {project}/openai/v1/responses` with `agent_reference` and the prompt "Read work item 1 …". The output contains `mcp_list_tools` → `mcp_call wit_work_item` → `message`.
2. **Write with approval:** ask the agent to update a wiki page. The output contains `mcp_approval_request` for `wiki_upsert_page`. Send a second call with `previous_response_id` and an input item `{"type": "mcp_approval_response", "approve": true, "approval_request_id": "<id>"}`.
3. **Audit:**
   - The wiki commit author is `doc-agent-spike (agent user)`.
   - The gateway log shows `authorized caller oid=<agent-identity-id>` and `rpc=tools/call tool=wiki_upsert_page`.

## Onboard another agent (automated)

[`infra/scripts/onboard-agent.ps1`](../../infra/scripts/onboard-agent.ps1) runs steps 2, 3, 4, 5.2 and 6.2 for an existing agent, then points the gateway at it. The script is idempotent: it skips any step that is already done, so it's safe to run again.

Prerequisites:
- The agent already exists and has the MCP tool from step 8.
- You are signed in with the Azure CLI as an account that can create users and grants in Entra and add users in Azure DevOps.

```powershell
./infra/scripts/onboard-agent.ps1 -AgentName <agent> `
    -ProjectEndpoint https://<account>.services.ai.azure.com/api/projects/<project> `
    -ResourceGroup <rg> -GatewayAppId <gateway-app-id> -AdoOrg <org> -AdoProject <project>
```

| Step | What it does | API |
|---|---|---|
| 1 | Reads `instance_identity` and `blueprint` of the agent | Foundry `GET agents/{name}` |
| 2 | Creates the agent user `<agent>@<default domain>` | [Create agentUser](https://learn.microsoft.com/graph/api/agentuser-post?view=graph-rest-1.0) |
| 3 | Gives Azure DevOps access: Basic + project Contributors (retries while the new user replicates) | [User entitlements REST](https://learn.microsoft.com/rest/api/azure/devops/memberentitlementmanagement/user-entitlements/add?view=azure-devops-rest-7.1) |
| 4 | Grants delegated consent for the agent user only | [Create oauth2PermissionGrant](https://learn.microsoft.com/graph/api/oauth2permissiongrant-post?view=graph-rest-1.0) |
| 5 | Adds the gateway's managed identity as a credential on the agent's blueprint | [Create federatedIdentityCredential](https://learn.microsoft.com/graph/api/application-post-federatedidentitycredentials?view=graph-rest-beta) |
| 6 | Assigns the gateway app role to the agent identity | [Grant an app role](https://learn.microsoft.com/graph/api/serviceprincipal-post-approleassignedto?view=graph-rest-1.0) |
| 7 | Re-points the gateway's environment variables, then waits for the new revision and `/healthz` | [`az containerapp update`](https://learn.microsoft.com/cli/azure/containerapp#az-containerapp-update) |

**Single-agent gateway:** the gateway serves **one** agent at a time. Step 7 switches it to the onboarded agent, and calls from any other agent get `403`. To serve several agents at once, deploy one gateway per agent (use `-SkipGateway` and your own deployment). Another option is to extend the gateway with an identity → agent user map.

How we verified it (2026-10-08):
1. We created a second agent, `doc-agent-test`, as a copy of `doc-agent-spike` v3. Before onboarding, its tool call failed with `AADSTS501051`.
2. After the script: it read work item 1 and created a wiki page after approval. The commit author was `doc-agent-test (agent user)`, and the gateway logged the new agent identity as the caller.
3. We ran the script again for `doc-agent-spike`. Every step reported "exists", and the gateway switched back.

## Agent identity lifecycle

| Event | Identity effect | What to do |
|---|---|---|
| Create a new agent | A new agent identity and blueprint | Run `onboard-agent.ps1` |
| New version of the same agent | Same identity and blueprint; our credential stays | Nothing |
| Publish to Microsoft 365 / Teams (new-model agent) | Same identity, according to [Learn](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications#agent-types-during-the-transition) | Nothing expected; verify in [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4) |
| Publish as a legacy *Agent Application* | A new, distinct identity ([Learn](https://learn.microsoft.com/azure/foundry/agents/how-to/agent-applications)) | Avoid; if you must, onboard that identity |
| Delete the agent | Foundry deletes the agent identity and blueprint. That also removes our credential, the app role assignment and the grant's client. | Offboard the agent user (below) |

**Offboard** an agent. We tested this on `doc-agent-test`.
1. Remove the agent user from Azure DevOps: Organization settings → Users, or `DELETE https://vsaex.dev.azure.com/{org}/_apis/userentitlements/{id}?api-version=7.1-preview.3`. This frees its Basic license.
2. Delete the agent user: `DELETE https://graph.microsoft.com/beta/users/{id}`. It stays in *Deleted users* for 30 days.
3. Delete the agent: `DELETE {project}/agents/{name}?api-version=2025-11-15-preview`. Its identity and blueprint disappear from Entra.
4. If the gateway pointed at this agent, run `onboard-agent.ps1` for the agent that should use it next.

## Gotchas we hit

| Symptom | Cause | Fix |
|---|---|---|
| `401` from `mcp.dev.azure.com` | The Azure DevOps REST audience was used | Use the audience/scope from `/.well-known/oauth-protected-resource/{org}` (`https://mcp.dev.azure.com`, appId `2a72489c-…`) |
| *"Identity … is currently Deleted"* | Azure DevOps rejects agent identity (app-only) tokens | Use the agent user via the gateway |
| `AADSTS65001` on T3 | No delegated consent for the agent user | Create the oauth2PermissionGrant (step 4) |
| `HTML 400 Bad Request` from upstream | The gateway forwarded ingress headers (`x-forwarded-*`, `x-envoy-*` …) | Forward only `content-type`, `accept`, `mcp-session-id`, `mcp-protocol-version` and `last-event-id` |
| Container Apps environment create fails in Sweden Central | `AKSCapacityHeavyUsage` (regional capacity) | Use another region (we used North Europe). Foundry calls the gateway over HTTPS. |
| The Azure CLI can't get a token for the gateway app | The Azure CLI is not a consented client of the custom API | Expected. Only the agent identity has the app role. |
| A new agent's tool call fails with `AADSTS501051` (*not assigned to a role for the application*) | Foundry can't get a token for the gateway because the new agent identity lacks the app role | Run `onboard-agent.ps1` (step 6) |
| A tool call fails with `403 Forbidden` from the gateway | The gateway points at a different agent (single-agent gateway) | Run `onboard-agent.ps1` for this agent |
| Azure DevOps error `5101` (*user from outside your directory*) right after the agent user is created | Entra → Azure DevOps replication delay | Retry after ~10–30 s; the script retries automatically |
| `az rest` fails on `applications(appId='…')` URLs on Windows | cmd mangles the parentheses and quotes | Use `Invoke-RestMethod` (as the script does) |

## Security notes (hardening comes later, per ADR 0020)

- The agent user has Basic + Contributors. Narrow this to a custom group with only wiki contribute and work item read.
- `tools/list` from Microsoft's server shows write tools even though only `wit.read` is granted. The gateway's `X-MCP-Toolsets` and the agent's `allowed_tools` limit what the agent can call. The server's per-scope enforcement is not verified yet.
- The gateway's ingress is public, but token validation is enforced. Consider private networking.
- Container logs go to the console only (`--logs-destination none`). Wire them to Log Analytics together with tracing.
