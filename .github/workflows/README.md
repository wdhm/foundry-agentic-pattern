# GitHub Actions

[`agent-evaluation-loop.yml`](agent-evaluation-loop.yml) is a separate opt-in
evaluation/improvement demo, not a replacement for the release workflow below.
Relevant main pushes and PRs run offline checks; only approved main runs can use
an explicitly isolated project for fresh model outputs and up to five candidates.
It never deploys, promotes, or continues to Teams. See
[isolated CI setup and bounds](../../evals/ISOLATED_CI.md).
The separately selected `supplied_sources_only` mode runs only the three existing
tools-disabled cases, needs no toolbox/source credentials, and can report only
`partial_passed` with `full_suite_passed=false`. Full mode remains the default;
manual selection must match the reviewed environment configuration.
The [paired precision/recall pipeline](../../evals/PRECISION_RECALL.md) has its own
explicitly selected `precision-recall` job after offline validation. It captures
whole pinned declared ADO trees and a real existing/approved wiki Markdown page,
then executes both chains and reports metrics without a release gate. It does
not invent a replay job or treat assessment JSON as a generated page. Dispatch
requires trusted main, both enable flags and protected environment approval;
PRs get no credentials. Raw artifacts and source-free Foundry publication each
have additional opt-ins, disabled by default.

The older [documentation-quality fixtures](../../evals/documentation-quality/README.md)
remain unit/regression examples, not the demo. Both new pipeline and older tests
run in the offline job with lint/type checks. Pushes changing
only that module, dataset/docs, or tests are excluded from the isolated job even
when enabled. Push eligibility uses the full before/after diff and the original
live-input path allowlist; PR credential exclusion and manual dispatch remain
unchanged. Missing initial-push history does not grant live eligibility.

[`agent-release.yml`](agent-release.yml) targets hosted **`documentation-agent`**.
It is the single platform-first MVP workflow
for the offline/code portion of #25/#26/#27. It is **manual dispatch only**.
There is no push, PR, merge, `pull_request_target`, promotion or rollback trigger.
#26 is consolidated here, not an untrusted-PR agent execution path.
The default job checks the P1/P3 suites and builds a Python wheel, not a
network-dependent container image. It never publishes the wheel or an image.
Python 3.13 matches P1's container runtime. The workflow installs the wheel
rather than an editable mapping so mypy can resolve the hosted package's
included `py.typed` marker; no type-error suppression is added.

Dispatch defaults to **offline regression tests only**, without Azure login or
OIDC permission. The cloud job was first dispatched successfully on 2026-10-20:
[run 39436721419](https://github.com/wdhm/foundry-agentic-pattern/actions/runs/39436721419)
evaluated candidate v19 to `eligible_for_manual_review`, and serving v13 was
untouched. That run wrote gate decisions and scores (no source content) to the job
summary. The current demo reporter publishes an allowlisted gate outcome instead
of interpolating arbitrary decision fields or per-case score payloads.
See [how to read the Actions demo](../../docs/workshop/evaluation-release-guide.md#reading-the-actions-demo)
for the two-job graph, internal runtime stages, and skipped-versus-evaluated semantics.

**Configured on 2026-10-20 (P2):**
- **Environment:** `p3-agent-release` with required reviewer @wdhm, restricted
  to the `main` branch.
- **Identity:** UAMI `id-gh-agent-release` in `rg-foundry-agentic-pattern`.
  Its federated credentials cover both GitHub OIDC subject formats:
  `repo:wdhm/foundry-agentic-pattern:environment:p3-agent-release` and the
  ID-based `repo:wdhm@253040606/foundry-agentic-pattern@1407061088:environment:p3-agent-release`.
  It has `Foundry User` on the Foundry account.
- **Variables:** the environment variables are set, and the repository variable
  `P3_RELEASE_ENABLED=true`.
- **Plans:** reviewed plans live in `evals/release-plans/`. A plan's serving-path
  proof is valid for one hour, so build and merge it immediately before dispatch.

**Security debt:** self-review is allowed, and the identity's role is broader
than needed. Tighten both in the hardening pass.
The optional cloud job requires all of: trusted `main`, successful offline checks,
explicit execution input, `P3_RELEASE_ENABLED=true`, and the separately configured
`p3-agent-release` environment approval. Opening this PR cannot start a cloud run.
Before login, local `--preflight-only` validates a reviewed evaluation plan and all
five canonical case envelopes. Missing isolated evaluation configuration or an
unreviewed evaluator/scope blocks. Local success is `local_preflight_passed` with
`cloud_readiness=not_checked`, never a live readiness certificate.
After separately approved execution, the runner verifies actual cloud/model/
serving state and creates an isolated evaluation candidate, using P1's opt-in
interface and observed-record scorer adapter. No live run was performed for this
implementation. Session GET/outer response disagreement or a missing outer
reference blocks evaluation; no candidate-execution proof is fabricated.
Ordinary assessment remains bare AgentRequest and is not silently switched.

Before an operator enables that job, configure environment required reviewers,
prevent self-review, restrict deployment branches to protected `main`, establish
federation for the exact environment subject, verify least-privilege Foundry
data-plane access, and set the non-secret environment variables
`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, and
`EVAL_MODEL_DEPLOYMENT`. Set the enable variable **last**, after approvals and
compatibility are verified. No environment, federation, role or model deployment
is configured by this change. The `P3_RELEASE_ENABLED` switch is a **repository**
variable so the job condition can read it before environment admission.
No credential secrets are used.

The runner requires a reviewed, expiring release plan, writer hold, exact live
serving-pin GET, model-version checks and explicit evaluator thresholds before
candidate creation. Passing means **eligible for manual evidence review**, never
promoted. The source-bearing evaluation version has `promotion_eligible=false`;
ordinary assessment rollout requires separate configuration/review.
Failed, missing, skipped and incomplete required evaluations block release.
Raw diagnostic artifacts may contain source content; upload additionally requires
`P3_ARTIFACT_PUBLICATION_APPROVED=true` after publication/access review. Access follows repository
artifact permissions and retention is three days. Do not enable cloud artifacts
on a public repository without a source-data publication review.

See the [evaluation/release automation guide](../../docs/workshop/evaluation-release-guide.md)
for the plan contract, interfaces, limits and outstanding live prerequisites.

**Owner:** P3 (AgentOps & platform): Louise ([@llandinl](https://github.com/llandinl))
