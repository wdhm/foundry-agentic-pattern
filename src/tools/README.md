# src/tools/

Tool and API integrations exposed to agents through a Foundry **Toolbox** (MCP) ([ADR 0011](../../docs/adr/0011-knowledge-foundry-iq-and-toolbox.md)).

## Implemented code

The primary P3 consumer is `documentation-trigger invoke` for hosted
`documentation-agent`; `--agent-kind prompt` retains the earlier `doc-agent`
compatibility path. [`hosted.py`](hosted.py) validates the reviewed container
digest/settings and actual P1 `AgentResult`, preserving application provenance
separately from Foundry deployment/session versions.
[`hosted_release.py`](hosted_release.py) provides offline preflight and mocked
candidate/readiness primitives; the full hosted gate blocks on unsupported suite
inputs/tool tracing before any cloud action. See the
[CLI](../../docs/workshop/cli-trigger-guide.md) and
[release guide](../../docs/workshop/evaluation-release-guide.md).

| Folder | What | Decision |
|---|---|---|
| [`ado_mcp/`](ado_mcp/README.md) | Gateway to Microsoft's remote Azure DevOps MCP server. The agent acts in Azure DevOps as its **agent user** (work items, wiki). | [ADR 0021](../../docs/adr/0021-agent-user-and-ado-mcp-gateway.md), [guide](../../docs/workshop/agent-identity-guide.md) |

## Tools the agent uses (MVP)

The following table describes the existing **prompt-agent** source configuration,
not proof of hosted toolbox access. Hosted assessment requires P2's four exact
read-tool names and separate identity/access review in the
[runtime guide](../agents/documentation-agent/README.md).
The scripts in [`infra/scripts`](../../infra/scripts) must not be used to repoint
the shared single-identity gateway without coordination.

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
