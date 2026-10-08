# Contributing

Thanks for contributing to **foundry-agentic-pattern**. This repo is a public reference pattern, so keep everything **generic, fictional and in English** ([ADR 0005](docs/adr/0005-generic-repo-with-fictional-data.md), [ADR 0019](docs/adr/0019-english-only.md)). Never commit customer names, real customer data or secrets.

## Workflow

1. **Pick or open an issue.** Use the labels `area:*` and `type:*`, and a milestone (M0–M4).
2. **Branch from `main`.** Name the branch `<type>/<short-description>`, for example `feat/contract-models`, `docs/adr-0020-retry-policy` or `spike/r3-agent-identity-ado`.
3. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/):
   ```text
   feat(contracts): add AgentResult evidence model
   fix(agent): reject tool call when approval hash mismatches
   docs(adr): add 0020 retry policy
   chore(infra): bump AI Search SKU
   ```
   Allowed types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`, `spike`.
   Suggested scopes: `contracts`, `agent`, `tools`, `infra`, `evals`, `data`, `samples`, `ci`, `adr`, `docs`.
4. **Open a pull request** to `main`:
   - Link the issue (`Closes #123`).
   - Describe *what* and *why*, and how you verified the change.
   - Keep PRs small and focused. One logical change per PR.
5. **Review.** At least one approval from the CODEOWNER of the area ([CODEOWNERS](.github/CODEOWNERS)) is required. CI must be green, including the eval gate for agent changes once it exists.
6. **Merge** with *squash and merge*. The PR title becomes the commit message, so it must follow Conventional Commits.

## Architecture Decision Records (ADRs)

Significant design decisions are recorded in [`docs/adr/`](docs/adr/README.md).

**When an ADR is required**
- Choosing or changing a platform, framework, service or region
- Changing the agent contract in a breaking way (bump `contract_version`)
- Changing identity, approval, audit or release/rollback behaviour
- Accepting a known risk or trade-off

**Process**
1. Copy [`0000-template.md`](docs/adr/0000-template.md) to `NNNN-short-title.md`, using the next free number.
2. Fill in **Context, Decision, Alternatives considered, Consequences**. Set the status to **Proposed**.
3. Add it to the index in [`docs/adr/README.md`](docs/adr/README.md).
4. Open a PR (`docs(adr): add NNNN …`). The owners of the affected tracks review it.
5. On merge, set the status to **Accepted**. ADRs are immutable after that. To change a decision, write a new ADR and mark the old one **Superseded by NNNN**.

## Spikes

Spikes (`type:spike`) answer a specific question with a **go/no-go** outcome. Record the result as an issue comment. If the outcome changes a decision, record it in an ADR or in [`docs/risks.md`](docs/risks.md).

## Document what you learn (every step)

This repo is also workshop material, so every setup or integration step we do must leave a written trail that others can repeat:

- **What we did:** the portal path or command, with placeholders instead of IDs and secrets.
- **What failed and why:** error messages and the fix (a "gotchas" table).
- **Official references:** link each step to **Microsoft Learn** (or other first-party docs). Check that the links resolve.
- **Where:**
  - environment values and the change log go in [`docs/setup.md`](docs/setup.md);
  - how-to and learnings go in [`docs/workshop/`](docs/workshop/) (e.g. the [agent identity guide](docs/workshop/agent-identity-guide.md));
  - decisions go in an ADR.

Do this in the same PR as the change.

## Code style (from M1)

- Python 3.11+, formatted and linted with `ruff`, and type-checked.
- Settings in [`.editorconfig`](.editorconfig).
- No secrets in code or config. Use managed identities and OIDC.
