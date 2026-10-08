# ado_mcp: agent-identity gateway to the remote Azure DevOps MCP server

Lets a Foundry agent use Microsoft's [remote Azure DevOps MCP server](https://learn.microsoft.com/azure/devops/mcp-server/remote-mcp-server) **as its own agent user**. Azure DevOps rejects agent identity tokens but accepts the agent's user account. See [ADR 0021](../../../docs/adr/0021-agent-user-and-ado-mcp-gateway.md) and the [workshop guide](../../../docs/workshop/agent-identity-guide.md).

```text
Foundry agent --(agent identity token, aud = this app)--> ado_mcp --(agent user token)--> https://mcp.dev.azure.com/{org}
```

| Module | Responsibility |
|---|---|
| `inbound_auth.py` | Accepts only the configured agent identity. It checks the issuer, audience (`api://<app>`), app role and `azp`/`appid`. |
| `agent_user_token.py` | Secretless [agent user OAuth flow](https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow): MI → T1 blueprint → T2 agent identity → T3 `user_fic`. Caches the token and refreshes it on upstream 401. |
| `proxy.py` | Forwards `/mcp` (POST/GET/DELETE) and streams responses (SSE). It forwards only MCP transport headers, sets `X-MCP-Toolsets`/`X-MCP-Readonly`, and logs the method/tool name (no content). |
| `server.py` | Wires it together (ASGI app for uvicorn). `GET /healthz` is unauthenticated. |

## Configuration (environment variables, no secrets)

| Variable | Meaning |
|---|---|
| `AZURE_TENANT_ID` | Tenant |
| `MCP_APP_CLIENT_ID` | AppId of the Entra app that represents this gateway (token audience) |
| `MCP_REQUIRED_ROLE` | App role the caller must have (default `Mcp.Tools.ReadWrite.All`) |
| `AGENT_BLUEPRINT_CLIENT_ID` | Agent identity blueprint appId |
| `AGENT_IDENTITY_CLIENT_ID` | Agent identity id (the only allowed caller, and the client in the user_fic flow) |
| `AGENT_USER_UPN` | The agent user's UPN |
| `MANAGED_IDENTITY_CLIENT_ID` | User-assigned MI that is a federated credential on the blueprint |
| `ADO_ORG` | Azure DevOps organization |
| `ADO_MCP_TOOLSETS` | Toolsets exposed upstream (default `wit,wiki`) |
| `ADO_MCP_READONLY` | `true` to expose only read tools (default `false`) |

## Run

```powershell
pip install -r requirements.txt --index-url https://packagefeedproxy.microsoft.io/pypi/simple
uvicorn ado_mcp.server:app --port 8000      # needs a managed identity for outbound calls
az acr build -r <acr> -t ado-mcp:<version> .  # container image (deployment: see the guide, step 7)
```
