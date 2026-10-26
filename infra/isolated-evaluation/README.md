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
The two original account roles have no wildcard actions, connection-secret/key access, agent writes,
model deployment management, role-assignment management, source access or
production grants. The custom operation names were checked against the live
Microsoft.CognitiveServices provider operation catalog.

Provider compatibility must be verified during the first live run. A missing
permission is a blocker to review explicitly, not permission to assign
`Foundry User` or Contributor to force a pass.

### Previously approved project-storage exception

The following records the original proposal, subsequently reviewed, explicitly
approved and applied through PR118. Its two actions and assignment are unchanged
by the evaluation-assets proposal below.

The first two bounded runs failed at project `/openai/v1/responses` with HTTP403,
before completing a candidate. This is not a quality verdict. The service did not
return a missing-operation code; the following is a **documented prerequisite
hypothesis, not a proven root cause or a working fix**.

Microsoft's [hosted agent permissions reference](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions#agent-access-beyond-defaults)
lists agent storage read/write alongside Responses permissions for project model
inference. For custom roles, it explicitly recommends `agents/*/read` and
`agents/*/write`: literal `agents/storage/read|write` operations are not registered
in the inspected provider catalog, so a supported exact storage-only grant has
not been established.

The proposed `main.bicep` delta creates one additional custom role, assignable
only inside `rg-foundry-evaluation-ci`, containing exactly:

```text
Microsoft.CognitiveServices/accounts/AIServices/agents/*/read
Microsoft.CognitiveServices/accounts/AIServices/agents/*/write
```

One new assignment grants that role **only to `id-gh-isolated-eval` at the exact
`foundry-eval-ci-r8n3ld/projects/evaluation-ci` project scope**. The existing
account-level inference/evaluation roles and project MI remain unchanged.
No top-level `agents/write`, endpoint interaction, keys/secrets, production
access, new models, capacity or resources beyond this role/assignment are added.

These child wildcards cover **more than storage**, including matching current or
future agent-child operations. They are a specific exception to the original
no-wildcard boundary and require explicit approval plus source review before
validation/deployment and one bounded verification run. Do not apply this source
as routine convergence until that approval is recorded. Do not grant the same
exception to the project MI speculatively.

Compile to stdout and pipe to `python infra/isolated-evaluation/assert-template.py`
to check the exact role, runner principal expression, project scope and unchanged
account-role boundaries. The assertion script reads ARM JSON only and makes no
Azure or model calls.

### Proposed evaluation-assets prerequisite: source only, not applied

Bounded run [40333586550](https://github.com/wdhm/foundry-agentic-pattern/actions/runs/40333586550)
on reviewed merge `0398e217b09371616f830a59e96514b0eb1730ee` completed all three
supplied-source cases (four agent requests, one correction), then failed before
submitting any judge group. At `judge_definition`, the service returned HTTP403
`UserError`, explicitly referencing
`Microsoft.CognitiveServices/accounts/AIServices/assets/write`, request ID
`24a6af20-33b0-4b53-8f97-2035f4325f3d`. The SDK call was `client.evals.create`
(`POST /openai/v1/evals` relative to the isolated project endpoint). This is an
observed evaluator-definition authorization prerequisite, not a model fix or a
quality verdict.

The exact proposed cloud delta is **one new custom role and one new assignment**:

| Boundary | Proposed value |
|---|---|
| Role name seed | `isolated-eval-project-assets` (separate from all existing roles) |
| Assignable scope | Only `rg-foundry-evaluation-ci` in subscription `ac021984-29ca-42e6-9c21-36e599814543` |
| Data actions | Exactly `Microsoft.CognitiveServices/accounts/AIServices/assets/write` |
| Management actions / exclusions | All empty; no wildcard, `assets/read` or `assets/delete` |
| Principal | Only CI runner `id-gh-isolated-eval`, object ID `0d421658-707e-463d-9644-d09efefef91d` |
| Assignment scope | `/subscriptions/ac021984-29ca-42e6-9c21-36e599814543/resourceGroups/rg-foundry-evaluation-ci/providers/Microsoft.CognitiveServices/accounts/foundry-eval-ci-r8n3ld/projects/evaluation-ci` |

The live provider operation catalog confirms `isDataAction=true` and display
name **Create a new version of an asset**. The published
[provider permissions reference](https://learn.microsoft.com/azure/role-based-access-control/permissions/ai-machine-learning#microsoftcognitiveservices)
describes generic asset operations; the live catalog's write description repeats read/list
wording, so the observed service denial and live display name are the more
precise evidence for this write requirement.

**This is not an evaluation-definition-only capability.** It authorizes generic
asset-version creation within this isolated project, including other asset types
that share that gate. The SDK exposes versioned datasets, custom evaluator
definitions and indexes; those are additional asset families to consider, not
an asserted exhaustive service authorization map. Neither provider metadata nor
the reviewed public documentation establishes a per-type restriction or an
exhaustive mapping of these endpoints to `assets/write`. Treat creation of other
project asset types, including dataset/evaluator/index versions where this gate
applies, as part of the permission's potential reach. This is not a new grant to
read upstream sources, ingest from protected external systems, create tool
connections or obtain connection credentials. It does not prevent a caller from
writing data it already holds into an asset version.

No original account role, inference permission, project managed identity,
approved agent-child pattern, model, gateway, production scope or existing
assignment changes. The new role has no account-scoped assignment. The compiled
assertions and negative regressions reject scope/principal drift, added
read/delete/wildcard/top-level-agent actions and changes to the prior patterns.

#### Subsequent read/list calls: inspected, not speculatively granted

The installed SDK and current `FoundryEvaluation.evaluate` call sequence is:
definition create, run create, run retrieve while pending, output-item list.
It does **not** explicitly retrieve/list evaluation definitions. The read routes
are `GET /openai/v1/evals/{eval_id}/runs/{run_id}` and
`GET /openai/v1/evals/{eval_id}/runs/{run_id}/output_items`. Existing runner
permissions already include OpenAI `evals/read` and AIServices
`evaluations/read`; the live catalog describes those as evaluation-run metadata
and evaluation-run reads. `assets/read` is separately registered for listing
versions/getting an asset version and is deliberately **not added**.

The [evaluation permissions guide](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-permissions)
supports equivalent custom permissions at the evaluation project, but does not
provide an exact per-endpoint action map. SDK routes do not establish every
internal service authorization check; whether subsequent calls also need
`assets/read` or another operation remains unverified. A further explicit denial
must be reviewed, not preempted with broader roles or extra actions.

Committing/merging this proposal authorizes no cloud writes or inference.
Keep `EVAL_LOOP_ENABLED=false` and raw artifact approval absent. Deployment, if
separately authorized after review, must use fresh validation/what-if and apply
only this role/runner-project assignment incrementally, not redeploy models or
modify existing roles. A subsequent bounded workflow run requires its own gate.

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
