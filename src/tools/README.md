# src/tools/

Tool and API integrations exposed to agents through a Foundry **Toolbox** (MCP) ([ADR 0011](../../docs/adr/0011-knowledge-foundry-iq-and-toolbox.md)).

> Placeholder. Implementation starts in **M2**.

## Planned tools

| Tool | Source | Access | Approval |
|---|---|---|---|
| Read file / tree at commit | GitHub (MCP) | read | none |
| Read PR diff | GitHub (MCP) | read | none |
| Read work item(s) | Azure DevOps (MCP/REST) | read | none |
| Read wiki page (current version) | Azure DevOps (MCP/REST) | read | none |
| **Update wiki page** | Azure DevOps (MCP/REST) | **write** | **`require_approval: always`** ([ADR 0008](../../docs/adr/0008-human-in-the-loop-approval.md)) |

## Pattern rules
- Every read tool returns an **exact version** (commit SHA, wiki page version/ETag, work item revision) so that it can be cited as evidence.
- Write tools are approval-gated, and the hosted runtime enforces the pause/resume ([R1](../../docs/risks.md#r1)).
- Least privilege per source ([ADR 0012](../../docs/adr/0012-agent-identity-and-rbac.md)).
- The wiki commit message includes the run ID and the approver.

**Owner:** P2 (Knowledge & identity)
