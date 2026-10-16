# src/tools/

Tool and API integrations exposed to agents through a Foundry **Toolbox** (MCP) ([ADR 0011](../../docs/adr/0011-knowledge-foundry-iq-and-toolbox.md)).

## Implemented code

| Folder | What | Decision |
|---|---|---|
| [`ado_mcp/`](ado_mcp/README.md) | Gateway to Microsoft's remote Azure DevOps MCP server. The agent acts in Azure DevOps as its **agent user** (work items, wiki). | [ADR 0021](../../docs/adr/0021-agent-user-and-ado-mcp-gateway.md), [guide](../../docs/workshop/agent-identity-guide.md) |

## Tools the agent uses (MVP)

All three are **MCP tools** on the agent, each backed by a Foundry project connection. Set them up with the scripts in [`infra/scripts`](../../infra/scripts); to point them at your own sources, see the [bring-your-own guide](../../docs/workshop/bring-your-own-guide.md).

| Agent tool | Server | Connection · identity | Reads / writes | Exact version for evidence | Guide |
|---|---|---|---|---|---|
| `ado` | Microsoft's remote Azure DevOps MCP, through the [`ado_mcp/`](ado_mcp/README.md) gateway (toolsets `wit`, `wiki`) | `ado-mcp-proxy` · **agent identity**, then the agent user | Work items, wiki pages; **wiki write** (`wiki_upsert_page`) with `require_approval` ([ADR 0008](../../docs/adr/0008-human-in-the-loop-approval.md)) | Work item revision; wiki page ETag (git blob ID) | [agent identity](../../docs/workshop/agent-identity-guide.md) |
| `github` | GitHub's hosted MCP server, read-only (`/mcp/readonly`), read tools allow-listed | `github-mcp` · fine-grained token, one repo | Files at a commit, pull requests and diffs | Full commit SHA (PR head SHA) | [GitHub MCP](../../docs/workshop/github-mcp-guide.md) |
| `knowledge` | Foundry IQ knowledge base MCP endpoint (`knowledge_base_retrieve`) | `kb-doc-agent-mcp` · **project** managed identity | Documentation standard (`DS-xx` rules) | Rule ID (the standard is a rule set, not evidence) | [Foundry IQ](../../docs/workshop/foundry-iq-guide.md) |

Who has which permission: [architecture §6](../../docs/architecture.md#6-identity--rbac-matrix).

## Pattern rules
- Every read tool returns an **exact version** (commit SHA, wiki page version/ETag, work item revision) so that it can be cited as evidence.
- Write tools are approval-gated, and the hosted runtime enforces the pause/resume ([R1](../../docs/risks.md#r1)).
- Least privilege per source ([ADR 0012](../../docs/adr/0012-agent-identity-and-rbac.md)).
- The wiki commit message includes the run ID and the approver.

**Owner:** P2 (Knowledge & identity): Rickard ([@wdhm](https://github.com/wdhm))
