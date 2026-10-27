# Hosted documentation-agent evaluation and release

**Offline evaluation integration, 2026-10-20.** Hosted **`documentation-agent`** is the primary
workshop/release target, per P3's direction and [ADR 0024](../adr/0024-hosted-documentation-runtime.md).
The former prompt `doc-agent` runner remains an explicitly selected compatibility
path. This package does not claim promotion, rollback or Teams delivery by the
release tooling.

## Reading the Actions demo

Open **Agent quality - validate, evaluate and improve** for the iterative demo,
or **Agent release - offline preflight and optional candidate evaluation** for
the hosted candidate preflight. The graph deliberately has only two jobs:
**1. offline validation** followed by **2. optional approved live evaluation**.
Expand each job for named checkout, dependency, test, lint, type, configuration,
identity and execution steps. Open the run summary for the plain-language
inputs/actions/outcomes stage map.

A green offline job means repository checks passed, **not** that the model
answered correctly. A grey/skipped live job means **not evaluated**; it is normal
for PRs, disabled environments, offline-only changes or default release dispatch.
An environment approval wait is not inference in progress. Coverage is shown in
the loop's reviewed-configuration and runtime summaries: `supplied_sources_only`
excludes the two live cases and tool-call accuracy, so `partial_passed` is never
a full-suite pass.

The execution step contains the actual runtime sequence: candidate inference,
structural/source/evidence checks, semantic judging, then a decision. The loop
can revise instructions after failure and evaluate up to five candidates.
Its shared single correction retry per case is schema/evidence repair, not
another unlimited optimization loop. The hosted release path evaluates a
candidate without instruction optimization. These internal phases are explained
in a table, **not represented as fabricated completed Actions steps**.
Existing deadlines, token budgets, schema constraints and quality thresholds
still apply. A blocked/interrupted result is not success; even an eligible
candidate requires separate manual review and is never automatically promoted.

Public summaries use fixed descriptions and allowlisted decisions; no model
answers, prompts, arbitrary case labels, source excerpts or raw errors are
rendered by the demo reporter. Restricted artifact publication remains behind
its existing separate approval flag. This UI change enables no cloud execution,
deployment, promotion, wiki write or Teams message.

## Live gate evidence (2026-10-20)

The full gate ran live twice against isolated candidates, with the same five
cases and the evaluator deployment `eval-gpt-5.4-mini`. Serving `documentation-agent:13`
stayed at 100% throughout, and both candidates were deleted afterwards.

| Case | Blocked candidate v17 (G / TA / TCA) | Passing candidate v18 (G / TA / TCA) |
|---|---|---|
| order-sync-retry (live) | 5 / 1 / 5 | 5 / 1 / 5 |
| order-sync-information-missing (live) | 5 / 1 / 5 | 5 / 1 / 5 |
| order-sync-dead-letter-stub | 5 / 1 / – | 5 / 1 / – |
| order-sync-wiki-unavailable | 4 / 1 / – | 4 / 1 / – |
| order-sync-version-isolation | **2 / 0 (blocked)** | **5 / 1** |

G = groundedness, TA = task adherence, TCA = tool-call accuracy.

- **Why v17 was blocked:** the version-isolation case asks for the retry and ERP
  timeout values. v17 only put them in evidence and did not state them, so task
  adherence failed. Its low groundedness came from a gate bug: the user query
  was sent as a plain string, so the evaluator saw an empty query.
- **What v18 changed:** v18 (image built from `d8bcf12`) states each requested
  fact in information reviews as a low-severity "Requested information" finding.
  The gate now sends evaluator queries as text items.
- **Gate decision:** v18 got `eligible_for_manual_review` with thresholds
  groundedness ≥ 3, task adherence = 1 and tool-call accuracy ≥ 3. It was
  `promoted=false` and `promotion_eligible=false`.

**Calibration notes:**
- `builtin.task_adherence` is binary: it returns 0 or 1 with the label pass or
  fail.
- Foundry rejects task adherence thresholds below 1, so the plan validator
  requires a threshold of exactly 1.
- The expected status in the deterministic source checks is exact, so model
  variance can still block. That counts as a failed gate, not a flaky test.

## Implemented, with live gates still required

| Surface | Behavior |
|---|---|
| `documentation-trigger invoke` | Defaults to hosted; validates reviewed immutable artifact and active assessment settings, creates a concrete-version session, sends only bare P1 `AgentRequest`, validates actual P1 `AgentResult` |
| `python -m tools.release` | Defaults to hosted; local `--preflight-only` never discovers credentials; explicit approved execution validates cloud state before candidate creation and evaluates all five cases |
| `tools.hosted_release.prepare_candidate` | Guarded immutable-version creation, bounded readiness and exact readback, retained concrete serving pin and writer hold |
| `tools.hosted_evaluation` | Canonical evaluation envelopes, exact source isolation, observed model/policy/schema correlation and built-in evaluator rows; no invented tool IDs or results |
| One manual workflow | Default offline P1/P3 regression + wheel build; optional cloud job remains off by default, with local plan preflight before login |
| Prompt compatibility | `--agent-kind prompt` on CLI; `--target prompt` on release; earlier append-only prompt runner/tests retained |

Ordinary assessment remains **bare AgentRequest / AgentResult**. Release evaluation
instead uses P1's separate [opt-in interface](../../src/agents/documentation-agent/EVALUATION_INTERFACE.md)
and authoritative `contracts.evaluation` models:

1. Live cases send the validated production request with explicit reviewed
   `request.task` scope and the original scenario question. They send no source,
   task or standard override in the outer evaluation envelope.
2. Supplied cases send only the case's pinned allowlisted snapshots and exact
   documentation standard, with UTF-8 SHA-256 digests. Omitted wiki sources stay
   unavailable; no snapshot or gold/reference answer becomes a live read.
   P1 enforces no toolbox/discovery, `tools=[]`, `tool_choice=none` and no function loop.
3. Successful reports must correlate request, result, execution, optional platform
   session and source mode; match canonical packaged instructions and actual
   provenance; and contain complete observed model calls. Supplied reports must
   echo the exact bundle and have no tools. Live reports must include all four
   discovered read schemas, successful policy results and matching observed model
   calls with unique real call IDs. Names/arguments/order and read policy/schema
   checks tie these records together; missing IDs are not synthesized.
4. Rows preserve actual model answers, calls and returned results. The final
   observed AnalysisOutput must assemble through P1's canonical helper to the
   unchanged returned AgentResult. Pinned live contents/versions, evidence excerpts
   and unchanged expected status are checked after invocation. No label enters
   model input. Context comes from observed live outputs or the exact supplied bundle.
5. Built-in groundedness/task adherence run for all five cases; tool-call accuracy
   applies only to the two observed live cases. All rows and explicit calibrated
   thresholds must pass; failures/missing results cannot produce eligibility.

P1 main at `89e8593` includes task-aware runtime app `0.4.0` and a separate
selected-proposal approval path. This branch preserves those contracts, generated
evaluation schemas, policies and tests. Assessment CLI supports optional paired
`--task-question` / `--task-scope`, forwarded as canonical `request.task`.
Evaluation requires `DOCUMENTATION_MODE=evaluation` **and**
`DOCUMENTATION_ENABLE_EVALUATION=true`, on a separately authorized isolated version.
Approval requires its own opt-in mode/policy; this CLI neither submits proposals
for execution nor resumes approval. This code does not enable any deployed version.

**Observed version discrepancy (P1 report, 2026-10-19):** deployed version 7
sessions GET as `version_ref=7`, while outer Responses reports
`agent_reference.version=6` (named serving pin). Runtime app `0.4.0` is not enough
to distinguish those image versions. The caller GET-confirms the created session,
preserves outer reference/session/response identifiers in stderr, and **fails
closed** on disagreement instead of producing candidate-version success.
Ordinary assessment still labels matching/absent references separately.
**Evaluation requires a matching outer reference as well as session GET**; absent,
malformed or conflicting reference blocks before scorer submission. Neither field
is a registry-image signature or a serving-path proof.
This discrepancy still needs platform/deployment investigation before a candidate
can be certified. No cloud reproduction was performed by this reconciliation.

The adapter is now integrated **offline**, not live-certified. Remaining live gates
are compatible evaluator deployment/version/capacity and calibrated thresholds,
isolated evaluation configuration/access, fresh serving proof/pin/writer hold,
resolved matching execution-version evidence, separate billable execution approval,
and hosted tracing/exporter/correlation proof. A local preflight pass establishes
none of these. The [hosted CLI](cli-trigger-guide.md) continues to support distinct
ordinary assessment smoke without treating it as full release certification.

## Smallest supported artifact and deployment sequence

Use the existing P1 container and shared project; no new IaC, project, model,
Cosmos store or APIM rollout. Keep build/publish separate from version creation
so reviewers know the immutable digest **before** the candidate is created.

1. Build from a reviewed source commit at repository root with P1's Dockerfile,
   targeting `linux/amd64`; run P1's local contract/assessment checks. The manual
   workflow currently builds the Python wheel offline, not a network-dependent
   container. P1/deployment owns image input fixes and actual container verification.
2. After separate build/publish approval, a trusted publisher with existing
   registry access builds/pushes the image and records the returned registry
   digest, source commit and build evidence. Do not put credentials in build
   arguments, plans or artifacts. A wheel alone is not a runnable hosted container.
3. Review `HostedArtifact`: immutable image `@sha256`, `source_commit`,
   `build_reference`, `readiness_review_reference`, actual P1 `runtime_provenance`.
   This association is an operator-reviewed attestation, not cryptographic proof
   that the registry image contains a particular source tree.
4. Construct the actual **stable SDK** hosted definition using
   `container_configuration: {image, registry_connection_id?}`,
   `protocol_versions: [{protocol: responses, version: "2.0.0"}]`, CPU/memory and
   the separately authorized evaluation environment below. The historical flat `agent.yaml` image/protocol
   keys are **not** the stable `HostedAgentDefinition` wire shape. Preserve registry
   auth, telemetry/RAI/session settings and nonrouting metadata from the reviewed base.
5. Only after full-suite capability, fresh coordinated writer hold, hosted serving
   pin/readback/runtime proof and separate billable approval: create one version
   using `project.agents.create_version(..., definition=HostedAgentDefinition(...))`.
   Record the actual returned version, poll that version to `active` with a bounded
   timeout, compare exact definition/metadata, and recheck the serving pin. This
   path is tested with doubles only here; no candidate was created for this change.
6. Evaluate the exact isolated candidate with fresh version-bound sessions. All five cases and all
   applicable built-in results are required. Only a complete passing gate can
   become eligible for **manual evidence review**, never promotion of the
   source-bearing evaluation version. `promotion_eligible=false` is explicit.
   Any rollout needs an ordinary assessment definition and separate release review;
   evaluation-mode results do not certify an unobserved assessment deployment.

The [official hosted CI quickstart](https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/set-up-cicd-hosted-agent?pivots=azd)
uses azd/OIDC and existing infrastructure. Its push trigger, automatic deploy and
nonempty smoke-response test are **not** this repo's release safety contract.
We deliberately keep manual-only dispatch, reviewed digest before creation and
strict P1 contract/evaluator checks. We do not scaffold an azd environment or
run `azd deploy` hooks that could affect serving selection.
The [azure.yaml reference](https://learn.microsoft.com/azure/foundry/agents/concepts/azure-yaml-reference)
supports a prebuilt `image:` path; any future azd adoption must preserve the
same digest/pin/hold/readback safeguards and inspect its hooks first.

## Assessment settings and ownership

| Configuration | Required value / owner |
|---|---|
| `DOCUMENTATION_MODE` | Explicit `assessment`; default `stub` is v0 and not an assessment |
| Evaluation candidate only | `DOCUMENTATION_MODE=evaluation` and `DOCUMENTATION_ENABLE_EVALUATION=true`, separately reviewed; serving must remain assessment with evaluation disabled |
| `DOCUMENTATION_AUTH_MODE` | Explicit `managed_identity` in Foundry; no local Azure CLI credential fallback |
| `DOCUMENTATION_PROJECT_ENDPOINT` | Exact existing Foundry project |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `DOCUMENTATION_MODEL_VERSION` | Reviewed existing chat deployment and actual revision; GET checked, not changed by P3 |
| `TOOLBOX_ENDPOINT` | Real P2 toolbox HTTPS MCP endpoint with hosted access |
| `DOCUMENTATION_ADO_PROJECT`, `DOCUMENTATION_ADO_WIKI` | Actual permitted ADO scope |
| `HOST`, `PORT` | `0.0.0.0`, `8088` |
| Protocol/resources/registry | P1 Responses 2.0.0, reviewed CPU/memory and existing registry connection/access |

P2 must expose exactly `knowledge___knowledge_base_retrieve`,
`github___get_file_contents`, `ado___wiki`, `ado___wit_work_item` and verify hosted
identity/model/toolbox/source access. The shared ADO gateway currently supports a
single selected agent identity: **no repointing or onboarding is part of this
alignment**. P1's read guards and evidence validation remain authoritative.
Assessment stays read-only. The PR #76 local approval spike used a dummy receipt.
Newer main also implements selected-proposal approval under its separate mode and
policy; it does not authorize assessment writes or make the P3 CLI an approval
client. Preserve P1's approval boundary and its own documented verification limits.

Native monitoring MI configuration and historical **prompt** trace ingestion alone
are not hosted instrumentation proof. **New historical v6 evidence (2026-10-20):**
the smoke owner reports an existing 19 October run with native response/session/
version 6, three application chat spans showing model
`gpt-6-luna-2026-09-22` and usage, tools/list plus five successful execute_tool spans
with matching tools/call children (IQ 1, GitHub 2, wiki 1, work item 1).
See [the sanitized trace record](../setup.md#hosted-native-trace-evidence-2026-10-20).
Do not double-count platform and application token spans. This proves those
historical v6 observations only, not exact arguments/schemas/results, tool accuracy,
new evaluation-mode ingestion or v7 execution binding. Caller IDs were only in
input message content, not dedicated structured fields. No new telemetry query,
source export or live invocation was performed for this adapter.

## Reviewed release plan and serving safeguards

`tools.hosted_release.HostedReleasePlan` reuses the existing `ReleasePlan`
approval/threshold fields rather than duplicating contracts. It requires:

| Field | Reviewed requirement |
|---|---|
| Project/name/base/serving versions | Exact hosted target; concrete positive integer Foundry versions, active base/serving and base still latest |
| `expected_endpoint`, `expected_identity` | Complete approved GET snapshots; exactly one concrete serving version at 100% |
| `candidate_definition` | Full nested stable SDK hosted definition; explicit evaluation mode/enable flag when `evaluation` config is present; image matches artifact |
| `artifact` | Strict `HostedArtifact` described above; P1 instruction/policy assembly validates provenance against installed source |
| `serving_path_proof` | Hosted name/version, fresh session/response IDs, timezone-aware observation within one hour, evidence reference and selection `fresh_named_endpoint_session_without_version_override` |
| Models/thresholds | Concrete chat/evaluator revisions and all three calibrated thresholds: groundedness 1..5, task adherence exactly 1 (binary evaluator), tool-call accuracy 1..5 |
| Approval/hold/evaluator references | Fresh explicit authorization, accountable reviewer, exclusive writer hold, evaluator compatibility evidence and future timezone-aware expiry |
| `evaluation` | Required for full gate; reviewed isolation reference, exact evaluator deployment, expected observed model name and explicit task scopes for every case |

The additional `evaluation` object contains no model choice defaults or live approvals:

```json
{
  "isolation_review_reference": "<reviewed test-version/access/privacy plan>",
  "evaluator_deployment": "<existing approved judge deployment>",
  "observed_model": "<reviewed expected model response identity, not necessarily its deployment alias>",
  "task_scopes": {
    "order-sync-retry": "change_review",
    "order-sync-information-missing": "information_review",
    "order-sync-version-isolation": "information_review",
    "order-sync-dead-letter-stub": "information_review",
    "order-sync-wiki-unavailable": "information_review"
  }
}
```

These task scopes express scenario intent, not expected status; reviewers must
approve them without changing the dataset or gold. `EVAL_MODEL_DEPLOYMENT` must
equal the reviewed field. Existing model/evaluator revision GET checks still apply.
The observed model identity is explicit because Responses model IDs need not be
the deployment alias; disagreement fails rather than being silently normalized.
An assessment-only plan without `evaluation` remains locally blocked for full release.

Proof references are **operator attestations**, not an authentication service,
distributed lock or atomic ETag guarantee. Obtain concrete hosted serving runtime
proof under the hold, without explicit-version/session bypass. Verify the pin
immediately before candidate creation. The former `doc-agent:3` pin approval was
paused and does not transfer to hosted `documentation-agent`.

Version-specific hosted test sessions deliberately bypass serving selection.
`get_openai_client(agent_name=...)` uses the agent's endpoint, and
`create_session(..., VersionRefIndicator(agent_version=C))` binds the candidate.
Responses uses `extra_body={"agent_session_id": returned_id}`. Check session
ID/binding/readiness before sending one serialized canonical request. Evaluation
adds `store=false` and `stream=false`. Existing sessions do not
migrate after selector changes. **Candidate-session success is not serving-path
runtime proof.**

There is no auto-pin, canary, promotion, rollback, role assignment or candidate/
session deletion. Preserve all nonrouting endpoint/identity/protocol/auth state.
GET rechecks detect drift but are not atomic with creation; all external writers
must hold. Follow [the manual routing runbook](release-rollback-guide.md) only
under fresh target-specific approval. Retain good versions/images and treat
interrupted candidates/sessions as manual investigation, not cleanup permission.

## Offline preflight and validation

```powershell
python -m pip install ".[agent,prompt,dev]"
python -m tools.release --plan "<reviewed-hosted-plan.json>" --output "evals/results/<fresh-directory>" --preflight-only
python -m pytest tests/release tests/evals tests/tools tests/contracts tests/agents -q
python -m ruff check src/tools tests/release tests/tools
python -m mypy src/tools/cli.py src/tools/hosted.py src/tools/hosted_evaluation.py src/tools/hosted_release.py src/tools/release.py src/tools/release_sources.py
python -m contracts.generate_schema --check
python -m pip wheel --no-deps --wheel-dir dist .
```

Preflight persists blocked diagnostics and exits nonzero for missing/invalid local
requirements. A complete reviewed plan can produce `local_preflight_passed`,
explicitly `cloud_readiness=not_checked`, without credentials or network calls.
Only separate approved execution with `--execute-approved-cloud` reaches cloud
preconditions/candidate/evaluator calls. Missing evaluator configuration/results never default to passing.
No default model or threshold is supplied. `EVAL_MODEL_DEPLOYMENT` was unset at
the previous observation; judge compatibility and calibrated criteria require
separately authorized work. The recorded quota 500/250 discrepancy and chat
`OnceNewDefaultVersionAvailable` policy are not resolved by version checks.
Coordinate model writers; pre/post GET cannot prevent an upgrade mid-run.

The [single workflow configuration](../../.github/workflows/README.md) requires
protected environment reviewers, no self-review, trusted main, environment-bound
OIDC federation, existing least-privilege data-plane/registry access and explicit
enable/execute switches. This code configures none of those. Source/evaluation
artifacts in this public repo require publication review; upload is gated by
`P3_ARTIFACT_PUBLICATION_APPROVED`, and retention is three days.

## Shared built-in evaluator contract and prompt compatibility

PR [#77](https://github.com/wdhm/foundry-agentic-pattern/pull/77) implemented the
original prompt release gate using merged CLI [#71](https://github.com/wdhm/foundry-agentic-pattern/pull/71)
and dataset [#72](https://github.com/wdhm/foundry-agentic-pattern/pull/72).
That code remains behind `python -m tools.release --target prompt ...`.
Its plan is the existing `tools.release.ReleasePlan`: prompt name, exact
base/serving snapshots, append-only instructions, inherited model/tools/schema/
policy metadata, approval/hold/evaluator compatibility, concrete models and
explicit thresholds. It is not used by the primary workflow and must not be
used to certify the hosted image.

Both adapters verify pinned live-source outputs; three source-bundle cases disable tools. Native approvals,
tool failures, invalid contracts and incomplete outputs block. Five cases are
submitted as precomputed JSONL `file_content` items to Foundry/OpenAI Evals,
using `builtin.groundedness`/`builtin.task_adherence` on all cases and
`builtin.tool_call_accuracy` on actual live calls/schemas only. Tools-disabled
cases are not applicable to tool scoring, not invented passes.
All completed rows, finite in-range scores, `passed=true`, valid labels and every
approved threshold are required. Missing/failed/skipped/duplicate/incomplete
results block. Model/serving checks precede eligibility. No baseline comparison
is claimed and gold/reference answers never become agent input.

The shared scorer maps `query`, `response` and discovered `tool_definitions` to all
three built-ins, `context` to groundedness and actual `tool_calls` to tool accuracy.
The hosted row uses native discovered function names, real model call IDs and
observed policy results in the documented message format; prompt compatibility
keeps its existing MCP conversion. Neither is a custom metric framework.
Evaluation records contain source-bearing data and are **not OTLP exports** or
proof of App Insights ingestion. Keep local reports private/ignored and review
publication before enabling artifact upload.

Official API sources:
[stable hosted image sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_create_hosted_agent_from_image.py),
[SDK models](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/azure/ai/projects/models/_models.py),
[session sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_sessions_crud.py),
[session Responses invocation](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_session_log_stream.py),
[cloud evaluator inputs](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets),
[evaluation results](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-results),
[agent evaluator scales](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/agent-evaluators).
[evaluator message/tool schema](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-dataset-schema).
