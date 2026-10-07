# .github/workflows/

GitHub Actions workflows ([ADR 0003](../../docs/adr/0003-github-for-code-and-cicd.md)).

> Placeholder. No workflows are active yet. They are added from **M1**.

## Planned workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | PR | Lint, unit tests, contract JSON Schema drift check |
| `documentation-agent.yml` | PR touching `samples/**` | Build an `AgentRequest` from the PR and invoke the agent. The result is posted to the PR and to Teams. |
| `agent-release.yml` | Merge to `main` (agent paths) | Build the container, create a new agent version, run the **eval gate**, then promote or block via `version_selector` |
| `post-deploy-rbac.yml` | After agent create/publish | Assign roles to the (new) agent identity ([R3](../../docs/risks.md#r3)) |

Authentication to Azure uses **OIDC workload identity federation**, with no stored secrets.

**Owner:** P3 (AgentOps & platform): Louise ([@llandinl](https://github.com/llandinl))
