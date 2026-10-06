# 0003. GitHub + GitHub Actions for code, PRs and CI/CD; Azure DevOps only as data source/target

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0006](0006-sources-and-trigger.md), [0013](0013-evaluation-gate-in-ci.md), [0012](0012-agent-identity-and-rbac.md)

## Context

The pattern needs a home for code, pull requests and CI/CD. Many enterprises keep their code in GitHub but still have documentation (wiki) and work tracking (Boards) in Azure DevOps. The demo should reflect that mixed reality without making the pattern depend on it.

## Decision

- **GitHub** hosts the code. **Pull requests** and **GitHub Actions** handle CI/CD, including the eval gate and agent releases.
- **Azure DevOps is not used for PRs or pipelines.** It is used only as a **data source/target**: the **wiki**, which the agent reads and (with approval) writes, and **work items**, which the agent reads.
- Azure authentication from GitHub Actions uses **OIDC workload identity federation**, with no stored secrets.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Azure DevOps Repos + Pipelines end to end | Fewer customers are standardising on it for new work, and it splits the story across two CI systems |
| GitHub only (GitHub wiki/issues as data) | Does not show cross-platform integration, which is a common enterprise reality |

## Consequences

- **Positive:** one CI/CD system. It mirrors typical enterprise landscapes and shows cross-system tool access.
- **Negative:** two systems need identity and access setup (see [R3](../risks.md#r3)).
- **Follow-ups:** workflows are defined in `.github/workflows/` (M1+).
