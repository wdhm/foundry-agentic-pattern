# GitHub Actions

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
OIDC permission. This implementation has not been dispatched against Azure.
The reserved cloud job requires all of: trusted `main`, successful offline checks,
explicit execution input, `P3_RELEASE_ENABLED=true`, and the separately configured
`p3-agent-release` environment approval. Opening this PR cannot start a cloud run.
Even with those switches, **current P3 evaluation-integration limits block before Azure
login**. `DOCUMENTATION_MODE=assessment` supports valid real-source smoke via
the CLI, but not three source-bundle cases or exported nested tool-call evidence.
The preflight never skips these requirements or certifies only two cases.
P1 now provides a separate opt-in evaluation mode with isolated supplied sources
and observed execution records. The login/evaluation steps are reserved for a
reviewed P3 transport/scorer integration and version-evidence validation, not
a working hosted release claim. Session GET/outer response disagreement is
explicitly surfaced and blocks candidate-version success.

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
candidate creation. Passing means **eligible for manual review**, never promoted.
Failed, missing, skipped and incomplete required evaluations block release.
Raw diagnostic artifacts may contain source content; upload additionally requires
`P3_ARTIFACT_PUBLICATION_APPROVED=true` after publication/access review. Access follows repository
artifact permissions and retention is three days. Do not enable cloud artifacts
on a public repository without a source-data publication review.

See the [evaluation/release automation guide](../../docs/workshop/evaluation-release-guide.md)
for the plan contract, interfaces, limits and outstanding live prerequisites.

**Owner:** P3 (AgentOps & platform): Louise ([@llandinl](https://github.com/llandinl))
