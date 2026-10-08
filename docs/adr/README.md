# Architecture Decision Records

We record significant design decisions as ADRs in a [MADR](https://adr.github.io/madr/)-style format: **Context, Decision, Alternatives considered, Consequences**. New ADRs start from the [template](0000-template.md). The process is described in [CONTRIBUTING.md](../../CONTRIBUTING.md#architecture-decision-records-adrs).

| # | Title | Status | Risks |
|---|---|---|---|
| [0001](0001-audience-and-delivery.md) | Audience is customer architects; repo is the product, workshop the delivery | Accepted | |
| [0002](0002-workshop-format.md) | Demo-driven workshop on a pre-deployed shared environment; attendees take the repo home | Accepted | |
| [0003](0003-github-for-code-and-cicd.md) | GitHub + Actions for code/PRs/CI/CD; Azure DevOps only as data source/target | Accepted | |
| [0004](0004-documentation-agent-story.md) | Documentation Agent story | Accepted | |
| [0005](0005-generic-repo-with-fictional-data.md) | Generic repo, fictional sample data, swappable documentation standard | Accepted | |
| [0006](0006-sources-and-trigger.md) | Sources and trigger; trigger-agnostic agent | Accepted | |
| [0007](0007-single-agent-in-v1.md) | One agent in v1; A2A as next step | Accepted | |
| [0008](0008-human-in-the-loop-approval.md) | Approval-gated wiki write; Teams Approve / Modify / Reject | Accepted | [R1](../risks.md#r1), [R2](../risks.md#r2) |
| [0009](0009-hosted-agent-runtime.md) | Foundry hosted agent with Microsoft Agent Framework | Accepted | [R1](../risks.md#r1), [R2](../risks.md#r2) |
| [0010](0010-python-and-pydantic-contracts.md) | Python; Pydantic contracts as single source of truth | Accepted | |
| [0011](0011-knowledge-foundry-iq-and-toolbox.md) | Foundry IQ for stable knowledge, Toolbox for versioned data | Accepted | |
| [0012](0012-agent-identity-and-rbac.md) | Entra Agent ID, least privilege; OBO as alternative | Accepted; refined by 0021 | [R3](../risks.md#r3) |
| [0013](0013-evaluation-gate-in-ci.md) | Ground-truth eval gate in CI | Accepted | [R2](../risks.md#r2) |
| [0014](0014-infrastructure-scope.md) | Infrastructure scope (`azd up` vs. docs only); phased by 0020 | Accepted | [R3](../risks.md#r3), [R4](../risks.md#r4) |
| [0015](0015-registry-foundry-fleet-management.md) | Registry: Foundry fleet management | Accepted | |
| [0016](0016-state-and-audit-cosmos-db.md) | State & audit in Cosmos DB | Accepted | [R1](../risks.md#r1) |
| [0017](0017-ownership-model.md) | Ownership: P1 / P2 / P3 tracks | Accepted | |
| [0018](0018-region-sweden-central.md) | Region: Sweden Central | Accepted | [R2](../risks.md#r2) |
| [0019](0019-english-only.md) | Everything in English | Accepted | |
| [0020](0020-manual-setup-first.md) | Manual Azure setup first ([runbook](../setup.md)); `azd` + Bicep in M4 | Accepted | |
| [0021](0021-agent-user-and-ado-mcp-gateway.md) | Azure DevOps as the agent user, via a gateway to the remote Azure DevOps MCP server ([guide](../workshop/agent-identity-guide.md)) | Proposed | [R3](../risks.md#r3) |
| [0022](0022-mvp-scope-platform-first.md) | MVP scope: show the platform, keep the flow simple (platform-native first, one happy path, hardening on slides) | Accepted (P2); proposed (P1, P3) | |
