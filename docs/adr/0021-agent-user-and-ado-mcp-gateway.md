# 0021. Azure DevOps access as the agent's user account, through a gateway to Microsoft's remote Azure DevOps MCP server

- **Status:** Proposed
- **Date:** 2026-10-08
- **Deciders:** P1, P2, P3
- **Related:** refines [0012](0012-agent-identity-and-rbac.md); [0008](0008-human-in-the-loop-approval.md), [0011](0011-knowledge-foundry-iq-and-toolbox.md), [0020](0020-manual-setup-first.md); risk [R3](../risks.md#r3); spike [#2](https://github.com/wdhm/foundry-agentic-pattern/issues/2); guide [agent-identity-guide.md](../workshop/agent-identity-guide.md)

## Context

[ADR 0012](0012-agent-identity-and-rbac.md) chose the agent's own Entra Agent ID identity. The R3 spike showed:

- Azure DevOps **rejects agent identity tokens** (app-only), both on the REST API and on the Microsoft-hosted remote Azure DevOps MCP server (`https://mcp.dev.azure.com/{org}`). The error is *"Identity … is currently Deleted"*.
- Azure DevOps **accepts the agent's user account** (agent user, `idtyp=user`). Its token comes from the [agent user OAuth flow](https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow): blueprint → agent identity → `user_fic`. This flow works without secrets when a user-assigned managed identity is a federated credential on the blueprint.
- Microsoft already hosts an [Azure DevOps MCP server](https://learn.microsoft.com/azure/devops/mcp-server/remote-mcp-server) with work item and wiki tools and fine-grained scopes (`wit.read`, `wiki.write` …).
- Foundry's MCP connection with `AgenticIdentityToken` sends only the agent identity token. It cannot do the `user_fic` exchange.

The product requirement: wiki and work item changes are made **by the agent, never by a person**, and run unattended.

## Decision

We will:

1. Give each agent an **agent user** (linked to its agent identity), licensed in Azure DevOps with only the project permissions it needs. Azure DevOps attributes all changes to it.
2. Run a **thin gateway** (`src/tools/ado_mcp`, Container Apps) between Foundry and `mcp.dev.azure.com/{org}`. The gateway:
   - accepts only the agent identity (Entra app + app role + caller check);
   - exchanges to an agent user token with its **user-assigned managed identity** (a federated credential on the blueprint, no secrets);
   - forwards MCP traffic unchanged. Only the transport headers are forwarded; the gateway sets the tool restrictions (`X-MCP-Toolsets`);
   - logs which tool the agent called.
3. Grant delegated consent **for the agent user only** (`Principal` grant) on the Azure DevOps MCP resource. The scopes are limited to what the agent needs (`Ado.Mcp.Tools wit.read wiki.read wiki.write`).
4. Connect the gateway to the agent through a Foundry project connection (`AgenticIdentityToken`, audience = gateway app). Use `allowed_tools`, and `require_approval: always` on write tools ([ADR 0008](0008-human-in-the-loop-approval.md)).

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Agent identity directly to Azure DevOps / remote MCP | No gateway | Azure DevOps rejects agent identities | Doesn't work today |
| Our own MCP server calling the Azure DevOps REST API (agent user) | Full control of the tool surface | We would write and maintain tools that Microsoft ships | More code for no gain |
| Remote MCP server via Foundry OAuth passthrough (catalog) | No code | Acts as a **signed-in person**; needs interactive consent | Contradicts the requirement |
| Project / user-assigned managed identity in Azure DevOps (ADR 0012 fallback) | Simple | Shared identity, not per agent; not the agent's identity | Weaker audit; the agent user works |
| Service principal + secret | Familiar | Secret management | Against [ADR 0012](0012-agent-identity-and-rbac.md) |

## Consequences

- **Positive:**
  - Per-agent attribution in Azure DevOps.
  - No secrets.
  - Microsoft maintains the tools; our code is only identity and policy (~250 lines).
  - Approval gating stays in Foundry.
- **Negative / trade-offs:**
  - One more runtime component (gateway) with an internet-facing endpoint.
  - The agent user needs an Azure DevOps license (Basic).
  - We add a federated credential to a **Foundry-managed blueprint**. It survives new agent versions; survival of Microsoft 365 / Teams publishing is not verified yet.
  - Every new agent gets its own agent identity, so the agent user, the grant, the app role and the gateway config are needed per agent. This is automated by [`onboard-agent.ps1`](../../infra/scripts/onboard-agent.ps1).
  - The gateway serves one agent at a time.
- **Follow-ups:**
  - M2: run `onboard-agent.ps1` from CI after deploy ([#28](https://github.com/wdhm/foundry-agentic-pattern/issues/28), [R3](../risks.md#r3)).
  - M4: Bicep for the gateway and identities ([#52](https://github.com/wdhm/foundry-agentic-pattern/issues/52)).
  - Hardening:
    - a narrower Azure DevOps group;
    - private ingress;
    - Log Analytics;
    - verify per-scope enforcement on the remote MCP server.
