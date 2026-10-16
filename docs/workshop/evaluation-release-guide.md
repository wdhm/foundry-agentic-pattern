# Hosted documentation-agent evaluation and release

**Offline alignment, 2026-10-16.** Hosted **`documentation-agent`** is the primary
workshop/release target, per P3's direction and [ADR 0024](../adr/0024-hosted-documentation-runtime.md).
The former prompt `doc-agent` runner remains an explicitly selected compatibility
path. This package does not claim a deployed assessment, live evaluation,
promotion, rollback, Teams delivery or completion of #13/#25/#27/#33.

## Implemented and deliberately blocked

| Surface | Behavior |
|---|---|
| `documentation-trigger invoke` | Defaults to hosted; validates reviewed immutable artifact and active assessment settings, creates a concrete-version session, sends only bare P1 `AgentRequest`, validates actual P1 `AgentResult` |
| `python -m tools.release` | Defaults to hosted; validates a strict reviewed plan and unchanged five-case suite; writes **blocked** diagnostics before any credential discovery/cloud work |
| `tools.hosted_release.prepare_candidate` | Offline-tested SDK primitive for guarded immutable-version creation, bounded readiness and exact readback; **not reached by the current CLI/workflow** |
| Hosted evaluator adapter | Uses the actual request/result for groundedness/task-adherence inputs; never wraps hosted output as prompt `AnalysisOutput` or invents tool traces |
| One manual workflow | Default offline P1/P3 regression + wheel build; optional cloud job is disabled by default and currently stops at unsupported-suite preflight before login |
| Prompt compatibility | `--agent-kind prompt` on CLI; `--target prompt` on release; earlier append-only prompt runner/tests retained |

**Two hard P1 dependencies prevent full hosted release certification:**

1. Assessment accepts **only bare AgentRequest v1**. The unchanged suite's three
   `supplied_sources` cases require isolated source snapshots with tools disabled,
   which P1 does not implement. Do not wrap a source envelope around AgentRequest,
   suppress internal tools with an outer `tool_choice`, change the gold, drop
   cases, or turn unavailable wiki content into a live wiki read.
2. P1 verifies nested tool evidence internally but returns only AgentResult in
   outer Responses. Actual correlated calls/results and discovered schemas are
   not exported. Outer Responses is therefore insufficient for pinned live-read
   verification or honest `builtin.tool_call_accuracy`. Neither prompt traces nor
   empty tool arrays count as hosted tool-call passes.

These are release-gate blockers, **not a blanket block on meaningful assessment
smoke**. The [hosted CLI](cli-trigger-guide.md) can invoke a valid assessment when
real P2 configuration/access exists. P1 must review source-isolation and correlated
trace support; P3 then wires it in a separate reviewed change. The current preflight
cannot be overridden by enable switches or `--execute-approved-cloud`; it does not
create a doomed candidate or incur evaluator costs.

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
   the assessment environment. The historical flat `agent.yaml` image/protocol
   keys are **not** the stable `HostedAgentDefinition` wire shape. Preserve registry
   auth, telemetry/RAI/session settings and nonrouting metadata from the reviewed base.
5. Only after full-suite capability, fresh coordinated writer hold, hosted serving
   pin/readback/runtime proof and separate billable approval: create one version
   using `project.agents.create_version(..., definition=HostedAgentDefinition(...))`.
   Record the actual returned version, poll that version to `active` with a bounded
   timeout, compare exact definition/metadata, and recheck the serving pin. This
   primitive is mocked here; current hosted CLI release blocks before it.
6. Evaluate the exact candidate with fresh version-bound sessions. P1 source and
   tool-trace dependencies above must be resolved first. All five cases and all
   applicable built-in results are required. Only a complete passing gate can
   become eligible for **manual review**, never automatic promotion.

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
Assessment stays read-only. The PR #76 local approval spike uses a dummy receipt;
it is not real Toolbox approval enforcement, wiki publication or Teams completion.

Native monitoring MI configuration and historical **prompt** trace ingestion are
not hosted instrumentation proof. P1/P3 still need to verify runtime model/tool
instrumentation, exporter/auth configuration and hosted session/response/version
correlation in the existing App Insights connection. Do not claim the native
connection alone exports P1's internal guard calls/schemas.

## Reviewed release plan and serving safeguards

`tools.hosted_release.HostedReleasePlan` reuses the existing `ReleasePlan`
approval/threshold fields rather than duplicating contracts. It requires:

| Field | Reviewed requirement |
|---|---|
| Project/name/base/serving versions | Exact hosted target; concrete positive integer Foundry versions, active base/serving and base still latest |
| `expected_endpoint`, `expected_identity` | Complete approved GET snapshots; exactly one concrete serving version at 100% |
| `candidate_definition` | Full nested stable SDK hosted definition and explicit assessment settings; image matches artifact |
| `artifact` | Strict `HostedArtifact` described above; P1 instruction/policy assembly validates provenance against installed source |
| `serving_path_proof` | Hosted name/version, fresh session/response IDs, timezone-aware observation within one hour, evidence reference and selection `fresh_named_endpoint_session_without_version_override` |
| Models/thresholds | Concrete chat/evaluator revisions and all three calibrated thresholds: groundedness 1..5, task adherence 0..1, tool-call accuracy 1..5 |
| Approval/hold/evaluator references | Fresh explicit authorization, accountable reviewer, exclusive writer hold, evaluator compatibility evidence and future timezone-aware expiry |

Proof references are **operator attestations**, not an authentication service,
distributed lock or atomic ETag guarantee. Obtain concrete hosted serving runtime
proof under the hold, without explicit-version/session bypass. Verify the pin
immediately before candidate creation. The former `doc-agent:3` pin approval was
paused and does not transfer to hosted `documentation-agent`.

Version-specific hosted test sessions deliberately bypass serving selection.
`get_openai_client(agent_name=...)` uses the agent's endpoint, and
`create_session(..., VersionRefIndicator(agent_version=C))` binds the candidate.
Responses uses `extra_body={"agent_session_id": returned_id}`. Check session
ID/binding/readiness before sending one bare request. Existing sessions do not
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
python -m tools.release --plan "<reviewed-hosted-plan.json>" --output "evals/results/<fresh-directory>"
python -m pytest tests/release tests/evals tests/tools tests/contracts tests/agents -q
python -m ruff check src/tools tests/release tests/tools
python -m mypy src/tools/cli.py src/tools/hosted.py src/tools/hosted_release.py src/tools/release.py src/tools/release_sources.py
python -m contracts.generate_schema --check
python -m pip wheel --no-deps --wheel-dir dist .
```

Preflight intentionally exits nonzero and persists `decision.json` with blocked
dependencies. Missing evaluator configuration/results never default to passing.
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

## Historical prompt compatibility and evaluator contract

PR [#77](https://github.com/wdhm/foundry-agentic-pattern/pull/77) implemented the
original prompt release gate using merged CLI [#71](https://github.com/wdhm/foundry-agentic-pattern/pull/71)
and dataset [#72](https://github.com/wdhm/foundry-agentic-pattern/pull/72).
That code remains behind `python -m tools.release --target prompt ...`.
Its plan is the existing `tools.release.ReleasePlan`: prompt name, exact
base/serving snapshots, append-only instructions, inherited model/tools/schema/
policy metadata, approval/hold/evaluator compatibility, concrete models and
explicit thresholds. It is not used by the primary workflow and must not be
used to certify the hosted image.

The prompt adapter's two live-source cases verify all pinned read outputs and
Foundry IQ retrieval; three source-bundle cases disable tools. Native approvals,
tool failures, invalid contracts and incomplete outputs block. Five cases are
submitted as precomputed JSONL `file_content` items to Foundry/OpenAI Evals,
using `builtin.groundedness`/`builtin.task_adherence` on all cases and
`builtin.tool_call_accuracy` on actual live calls/schemas only. Tools-disabled
cases are not applicable to tool scoring, not invented passes.
All completed rows, finite in-range scores, `passed=true`, valid labels and every
approved threshold are required. Missing/failed/skipped/duplicate/incomplete
results block. Model/serving checks precede eligibility. No baseline comparison
is claimed and gold/reference answers never become agent input.

Official API sources:
[stable hosted image sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_create_hosted_agent_from_image.py),
[SDK models](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/azure/ai/projects/models/_models.py),
[session sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_sessions_crud.py),
[session Responses invocation](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_session_log_stream.py),
[cloud evaluator inputs](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets),
[evaluation results](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-results),
[agent evaluator scales](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/agent-evaluators).
