# Real Azure DevOps sources and real assessment output

For the newer **whole-repository precision/recall pipeline**, start with
[PRECISION_RECALL.md](PRECISION_RECALL.md). This page describes only the earlier
five-file assessment capture and its still-relevant authentication prerequisites.
It is not the whole-source/page-evaluation demo.

`python -m tools.sandbox_eval` connects **actual Azure DevOps GET responses** to
the existing assessment runtime, contracts, evidence checks, execution capture
and Foundry groundedness/task-adherence judges. It does not create another mock
agent, replace the curated baseline, invoke the serving agent, or publish a wiki.
The [existing isolated loop](ISOLATED_CI.md) remains unchanged by default.

There are two deliberately separate steps:

1. **Capture:** a dedicated application identity GETs at most five exact repository
   files at one commit and one wiki page at a wiki commit plus expected page ETag.
   The reader checks returned paths, code commit/blob hashes and wiki ETag/content
   hash. Redirects, arbitrary URLs, branch/latest references, writes and automatic
   retries are not accepted. Application mode remains the default; delegated
   users require the separate manual-only approval described below.
2. **Evaluate:** the checked-out assessment agent calls the isolated Foundry
   candidate model using those captured sources, with tools disabled. The existing
   runner captures actual model response IDs, instructions, schema/evidence
   checks and output; the existing judges score that actual output. The reviewed
   expected status is checked locally, never supplied to the agent.

This is **GET capture -> real agent -> real judges**, not agent-driven retrieval.
Tool-call accuracy is **not evaluated**. `sandbox_passed` never means
`full_suite_passed`, a release approval, a published page, generalization, or human
calibration. The five original cases and curated three-case offline scoring
examples are retained. The transport tests use synthetic responses and are not
evidence of a live Azure DevOps or model execution.

## Current discovery and exact authorization blocker (2026-10-27)

The existing documented examples are in
[`foundry-agentic/integration-team`](https://dev.azure.com/foundry-agentic/integration-team),
repository `integration-team`, wiki `integration-team.wiki`, page
`/Order Sync/Overview`. Reuse of these examples **read-only** was approved.
Authenticated project discovery with the current desktop CLI user returned
**HTTP 401**; this change does not claim that their current code or wiki was
retrieved or evaluated. Historical GitHub source fixtures are not proof that the
same paths/commits exist in Azure Repos. Do not copy their pins into the sandbox
plan or provision duplicates without checking the actual example repository.

Read-only ARM discovery identified the existing evaluation runner:

| Property | Verified value |
|---|---|
| Managed identity | `id-gh-isolated-eval` |
| Resource group | `rg-foundry-evaluation-ci` |
| Subscription | `ac021984-29ca-42e6-9c21-36e599814543` |
| Tenant | `cc48e4fe-6662-414d-aeff-4eb633735b38` |
| Application/client ID | `8c257121-e197-47c1-b141-c2dd663ac14d` |
| Service principal/object ID | `0d421658-707e-463d-9644-d09efefef91d` |

The organization's unauthenticated `X-VSS-ResourceTenant` response header matches
that tenant. This establishes tenant compatibility, **not Azure DevOps membership,
effective permissions, login as that identity or successful reads**. No identity,
license, role, ACL, resource, source data or workflow settings were changed.

### Administrator action needed before capture

Use the existing UAMI rather than the production agent user, production token
exchange or shared toolbox:

1. In `foundry-agentic` **Organization settings -> Users -> Add users**, onboard
   `id-gh-isolated-eval` as the managed identity/service principal above, using
   **Basic** access if required for private Azure Repos. This can consume a
   license; an administrator must approve it. Do not add it to Contributors or
   Project Administrators. Select the exact tenant/object, not a similarly named
   application registration. If the UI cannot resolve a managed identity, an
   organization administrator should use the supported service-principal
   entitlement onboarding API; do not substitute the production agent user.
2. In **Project settings -> Repositories -> integration-team -> Security**, grant
   that principal only repository **Read**. Grant the minimum **View
   project-level information** permission needed for that project. Do not grant
   Contribute, Create branch/tag, Force push, Manage permissions, work-item writes
   or collection-wide readers. Inspect inherited groups: a direct Read grant
   does not remove inherited write privileges.
3. Give **Read** on the wiki's actual backing Git repository only
   (`integration-team.wiki` for the documented project wiki). Do not grant wiki
   Contribute, rename/delete, or approval/publishing rights. Confirm the backing
   repository in Wiki security rather than assuming every wiki uses that name.
   Git Read is repository-scoped; the CLI adds exact-file/page boundaries, not
   a claim that Azure DevOps implements path-level Git Read ACLs.
4. On an execution host already permitted to use this UAMI, sign in with that
   managed identity. The existing GitHub environment's OIDC credential can also
   sign in as it, but this PR adds no dispatch or workflow modification. Do not
   create federation, attach identities to hosts, widen IAM, or reuse user
   credentials just to bypass this blocker. The CLI rejects tokens whose tenant,
   object, client or ADO audience differs from the plan.
5. Review the example repository's actual file paths and commit in **Repos ->
   Files**. Review the wiki backing repository commit and GET the page at that
   commit to record its ETag (page Git blob ID, **not** the wiki commit).
   Set an expected status only after reviewing those exact sources. Record the
   approval and expectation review references in the plan.

See Microsoft's [managed identity/service principal Azure DevOps guidance](https://learn.microsoft.com/azure/devops/integrate/get-started/authentication/service-principal-managed-identity)
and [repository permissions](https://learn.microsoft.com/azure/devops/repos/git/set-git-repository-permissions).
An HTTP 401/403 is an operational blocker, not a quality failure to optimize.

## Runnable path after authorization

Install the existing extras into the chosen Python environment:

```bash
python -m pip install -e '.[agent,prompt,dev]'
```

Copy [`sandbox-plan.example.json`](sandbox-plan.example.json) to a **private**
working directory and replace all `REPLACE_...` placeholders. It is intentionally
not runnable until exact ADO code/wiki pins are reviewed. `expected_status` is an
illustrative expectation, not a claim about the existing sources. Supported
plans use one project, one repository, one wiki page, at most five files and no
work items. Missing/unavailable/error responses fail capture instead of using
fixtures. This CLI does not seed or modify the approved existing examples.

After login as the approved identity, capture once:

```bash
SANDBOX_READ_APPROVED=true python -m tools.sandbox_eval capture \
  --plan /private/sandbox-plan.json \
  --output /private/sandbox-capture.json \
  --capture-approved-readonly
```

Use the already reviewed `supplied_sources_only` isolated configuration, not a
production toolbox configuration. The known isolated project is
`https://foundry-eval-ci-r8n3ld.services.ai.azure.com/api/projects/evaluation-ci`,
candidate `eval-candidate-full` / `2026-03-05`, observed response model
`gpt-5.4-2026-03-05`, judge `eval-judge` / `2026-03-17`. Re-read deployment metadata
before execution; existing configuration also pins the optimizer even though
this command never calls it. Both ADO domain labels must match the capture plan.

With explicit approval for this bounded paid invocation:

```bash
EVAL_LOOP_APPROVED=true python -m tools.sandbox_eval evaluate \
  --plan /private/sandbox-plan.json \
  --capture /private/sandbox-capture.json \
  --config /private/isolated-loop-config.json \
  --output /private/sandbox-run-001 \
  --execute-approved-isolated
```

Evaluation preflights `model_identity` (or, for existing application plans only,
`read_identity`) using a Foundry-audience token. Keep that CLI identity
selected for the entire run; do not concurrently switch accounts in the shared
CLI cache. The existing runner creates fresh CLI credentials for individual
assessment calls. A token preflight is not a recorded service-side principal
attestation for every response.

## Manual capture with Sasha's own login

Basic organization membership is **not** repository Read permission or admin
access. Sasha must personally sign in; do not share credentials, select another
person's cached login, reuse production identities, or grant permissions here.
Both desktop and WSL CLI inspection currently show a different tenant
(`72f988bf-86f1-41af-91ab-2d7cd011db47`), so no authenticated ADO reads were
attempted for this follow-up. Interactive sign-in and verified source permissions
remain blockers; exact code/wiki pins are still unverified.

In a private copy of the example plan, replace `read_identity` with:

```json
{
  "mode": "delegated_user",
  "tenant_id": "cc48e4fe-6662-414d-aeff-4eb633735b38",
  "object_id": "cbc26d4a-7626-45bc-bd50-c2161c41bd71"
}
```

Also set `model_identity` to the existing approved isolated UAMI's
tenant/object/client IDs from the table above (optionally `"mode": "application"`)
and `model_identity_review_reference` to the reviewed Foundry permission evidence.
These are separate identities; source capture does not grant model access.
Explicit model identities always require that review reference. A delegated
model identity is supported only with separately reviewed, verified isolated
Foundry permissions and the same manual opt-in, never CI.

Use an existing Python environment with the repository's extras available.
This Bash subshell uses a new private CLI cache, not the shared Azure default.
Sasha completes the interactive login as
`SashaO@M365CPI54615665.OnMicrosoft.com`:

```bash
(
  export AZURE_CONFIG_DIR="$(mktemp -d)"
  chmod 700 "$AZURE_CONFIG_DIR"
  az login --tenant cc48e4fe-6662-414d-aeff-4eb633735b38 --allow-no-subscriptions
  SANDBOX_READ_APPROVED=true SANDBOX_MANUAL_USER_APPROVED=true \
    python -m tools.sandbox_eval capture \
      --plan /private/sandbox-plan.json --output /private/sandbox-capture.json \
      --capture-approved-readonly --manual-user-approved
)
```

Retain/manage the private cache according to local credential policy; do not
commit it. No `az account set`, shared default mutation, or `az logout` is needed.
Tokens are obtained by `AzureCliCredential`; decoded claims are only a usage
guard, **not signature authentication**. Exact audience, tenant and user object
plus nonempty delegated `scp` are required, and `idtyp=app` is rejected. CLI
`appid`/`azp` identifies the client, not Sasha. User mode rejects CI/GitHub Actions
even with both approval switches.

For evaluation, use the earlier evaluate command from a separate session/cache
already authorized as the reviewed isolated model identity. No model run is
automatic or authorized by read approval. If explicitly reviewed user-mode model
execution is chosen instead, add `SANDBOX_MANUAL_USER_APPROVED=true` and
`--manual-user-approved` to that command in Sasha's private login subshell.
Capture identity remains in the replay file; the manifest records both source
and model identity and the model review reference. Changing identity or pins
invalidates the plan digest. Local hashes remain unsigned provenance, not remote
attestation. Keep the chosen model cache stable for all assessment and judge calls.

Run from the checked-out repository using a clean, committed `src`,
`data/knowledge` and `pyproject.toml`. The manifest freezes source/config/capture
hashes and the code commit; each evaluation regenerates request/correlation IDs.
Existing output paths are rejected. The capture is local evidence, **not a signed
attestation** against someone editing the file and its hashes. Keep it restricted.

One candidate, one case, no optimizer or promotion. Existing limits allow at most
one schema/evidence correction (two model calls), 4,096 output tokens per call
and a 180-second case deadline. Sources are capped at 80,000 UTF-8 bytes; the
existing runner also enforces its complete 150,000-byte model-input limit. GETs
have 30-second per-request deadlines, a 200,000-byte response limit and at most
six requests. A single judge group scores groundedness >= 3/5 and task adherence
= 1. The overall evaluation deadline is 25 minutes; submitted remote judge work
can outlive cancellation. These are execution bounds, **not a guaranteed dollar
cap**. Existing isolated quotas/budgets and approval are still required.

Outputs include `manifest.json`, the real invocation/execution captures, real
assessment output, judge inputs/results and `decision.json`. A failed operation
exits nonzero; an evaluation failure retains a blocked decision, never a success
verdict. CLI error text omits upstream bodies and raw model/source content.
Raw artifacts are not uploaded or committed. Use a private output directory:
captures use mode `0600` and run directories `0700` where supported.
Repository-internal output is accepted only at a new, Git-ignored path below
`evals/results/`, with no tracked files at or beneath that path (including deleted
tracked files). Other internal paths are rejected before reading inputs,
obtaining credentials or writing artifacts. Symlinks are resolved before this
check; external private paths remain supported.
Deserializing a capture verifies each `SourceSnapshot` content SHA-256, so editing
Git content without updating its digest is rejected. Someone able to rewrite
both captured Git content and its digest can still produce a locally consistent
capture: these hashes do not independently attest membership in the named remote
commit. Preserve the trusted capture file and its externally recorded hash.
No automatic evaluation enablement, production permissions, serving routing,
assessment-only rules or publication approvals are changed.
