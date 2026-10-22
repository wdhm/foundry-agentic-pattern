# Isolated supplied-source evaluation infrastructure

**Proposed, not deployed by committing this directory.** Provision only after
source review and the prepare -> validate -> deploy handoff.

## Exact proposed effects

| Item | New resource/configuration |
|---|---|
| Subscription / tenant | `ac021984-29ca-42e6-9c21-36e599814543` / `cc48e4fe-6662-414d-aeff-4eb633735b38` |
| Resource group / region | `rg-foundry-evaluation-ci` / `swedencentral` |
| Account / project | `foundry-eval-ci-r8n3ld` / `evaluation-ci` |
| Auth / network | Entra only (`disableLocalAuth=true`); public endpoint for GitHub-hosted runners |
| Candidate deployment | `eval-candidate`: `gpt-5.4-mini`, version `2026-03-17`, GlobalStandard capacity 50 |
| Judge deployment | `eval-judge`: same model/version, independent capacity 50 |
| Optimizer deployment | `eval-optimizer`: same model/version, independent capacity 10 |
| Upgrade / safety policy | `NoAutoUpgrade`, `Microsoft.DefaultV2`; dynamic account throttling disabled |
| CI identity | New UAMI `id-gh-isolated-eval` |
| Federation | Only `https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange`, exact immutable repository/environment subject below |
| Project identity | New system-assigned project MI, inference-only role on the new account |
| CI RBAC | New narrow custom role on the new account, detailed below |
| GitHub environment | New `isolated-agent-evaluation`, custom branch policy matching only `main` (no tags); no required per-run reviewer |
| GitHub variables | New environment variables for UAMI client/tenant/subscription and `EVAL_LOOP_CONFIG`; repository `EVAL_LOOP_MODE=supplied_sources_only`; `EVAL_LOOP_ENABLED=true` only after isolation verification |
| Artifact publication | Leave `EVAL_LOOP_ARTIFACTS_APPROVED` unset unless publication of diagnostic output is separately approved; summary remains available |

Exact federated subject (confirmed through the repository's OIDC configuration):

```text
repo:wdhm@253040606/foundry-agentic-pattern@1407061088:environment:isolated-agent-evaluation
```

The environment's main-only branch policy and the workflow's main/non-PR check
are both required: an environment OIDC subject does not encode the branch.
The user explicitly approved automatic paid bounded evaluation, so this isolated
evaluation-only environment has no required per-run reviewer. Source and setup
review remain required before activation. Existing release and production
environment protections must not be changed.

`main.bicep` creates no toolbox, connection, Search, storage, hosted agent,
Container App, registry, APIM resource or production assignment. It has no
`existing` production references and is intended only for the new resource group.
Verify that the proposed names are unused before creation; never adopt or
overwrite an existing unrelated resource. Use incremental deployment only.
No existing resource or role assignment is deleted.
Project creation precedes model deployment, and the three model writes are
serialized because Cognitive Services rejects concurrent parent-account writes.

## Least-privilege role payload

The CI UAMI receives only account/project/deployment metadata reads, the
OpenAI/AIServices `responses/read` and `responses/write` data actions, deployment
metadata reads, chat-completions inference, and OpenAI `evals/read|write` plus
AIServices `evaluations/read|write` on **the new account only**.
The project MI receives only model metadata and inference operations.
Both custom role definitions are assignable only inside the new resource group.
There are no wildcard actions, connection-secret/key access, agent writes,
model deployment management, role-assignment management, source access or
production grants. The custom operation names were checked against the live
Microsoft.CognitiveServices provider operation catalog.

Provider compatibility must be verified during the first live run. A missing
permission is a blocker to review explicitly, not permission to assign
`Foundry User` or Contributor to force a pass.

## Capacity and costs

Read-only quota inspection found GlobalStandard gpt-5.4-mini usage 150/limit 1000
in Sweden Central before setup; this proposal adds 110 units without reducing or
reassigning any existing deployment. The regional model catalog supports this
model/version and SKU. Recheck immediately before deployment.
No gpt-6-luna capacity is requested. Quota availability is not a capacity guarantee.
GlobalStandard model calls are paid; quotas are rate limits, not spending limits.
The existing five-candidate, request/token and wall-clock bounds still apply.

## Validation and activation order

1. Review/merge source and this exact resource/IAM proposal.
2. Compile Bicep and run focused tests; verify demo subscription/tenant, name
   availability, current model SKU/version/quota, provider operations and operator
   deployment/role permissions. Record the prepare/validate result.
3. Through azure-deploy, create **only** the named new resource group, validate/
   what-if the template, then deploy incrementally after checking it creates only
   the listed resources. No production update is allowed.
4. Read back the account's Entra-only auth, project/MI IDs, all three concrete
   model versions/SKUs/capacities, exact federated subject and custom role scopes.
   Confirm the new project has no connections, toolboxes or source grants.
5. Create the isolated GitHub environment with no required per-run reviewer and a main-only/no-tags branch policy;
   read those protections back. Preserve `p3-agent-release` and its variables.
6. Set client/tenant/subscription variables and the reviewed
   `supplied-demo-config.json` (replace the review reference with the actual
   reviewed PR/approval evidence). Set repository `EVAL_LOOP_MODE`; set
   `EVAL_LOOP_ENABLED` last. Do not add source credentials.
7. Dispatch the merged workflow on `main` with
   `evaluation_mode=supplied_sources_only` and report its actual outcome and exact
   run/SHA/candidate/model lineage.

`supplied-demo-config.json` requires **no toolbox endpoint**. ADO project/wiki
names are instruction-domain labels only, not connection targets or credentials.
The serving project URL is a deny target, never a request destination.

A successful partial run reports `partial_passed`, `full_suite_passed=false`,
and excludes `order-sync-retry` and `order-sync-information-missing`.
The unchanged full-suite mode remains blocked until dedicated genuinely
read-only upstream source authentication exists; this infrastructure does not
resolve that prerequisite.
