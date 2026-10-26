# Isolated evaluation and improvement demo

`agent-evaluation-loop.yml` is independent of the existing manual release workflow.
It never deploys a container or Foundry agent version, changes a serving selector,
merges code, writes a wiki, or sends Teams messages. It executes the checked-out
assessment code locally on the runner, using real model calls and the read-only
evaluation adapters. It does not score saved captures as if they were new outputs.

## Explicit partial demo mode

The default `mode=full_suite` is unchanged. A separately approved
`mode=supplied_sources_only` runs exactly the three existing supplied-source cases
with unchanged inputs, expected statuses and thresholds. It excludes
`order-sync-retry` and `order-sync-information-missing`; tool-call accuracy is
**not evaluated**. A successful partial gate reports `partial_passed` and
`full_suite_passed=false`, never full-suite quality approval or promotion.

In partial mode no toolbox endpoint or source credentials are accepted or used:
tools are disabled, no toolbox is imported/constructed/discovered, and only the
isolated model/project and judge APIs are called. ADO project/wiki names are
domain labels for the unchanged instructions, not remote connection settings.
Artifacts, feedback, decision and summary identify selected/excluded cases.
The runner still evaluates at most five candidates and fails fast on operational,
schema, source-integrity and authentication errors.

Set repository `EVAL_LOOP_MODE=supplied_sources_only` for automatic main runs.
Manual dispatch must select that same mode; mismatch with the approved config
fails before login. Mode changes are operator-reviewed configuration, not a
fallback when the full suite fails. Keep full mode blocked until genuine
read-only upstream access exists. See the
[isolated model/project/IAM proposal](../infra/isolated-evaluation/README.md)
and [partial configuration](../infra/isolated-evaluation/supplied-demo-config.json).

## Loop contract

1. Freeze the checkout SHA, source/data hashes, model versions and three thresholds.
2. Evaluate the initial candidate using all five existing cases: two read-only
   live-tool cases and three tools-disabled supplied-source cases.
3. Require groundedness >= 3/5 and task adherence = 1 on every case; require
   tool-call accuracy >= 3/5 only on the two live-tool cases. Exact expected
   statuses and the existing source/schema checks are additional requirements.
4. On completed low-quality results, ask the optimizer for revised **additional
   instructions only**, then evaluate fresh outputs with those instructions.
   The optimizer receives diagnostics, not file-edit access. It cannot change
   the checkout, policy, tools, judges, thresholds, dataset or expected answers.
5. Stop on pass, infrastructure/auth/schema/source failure, empty/oversized/repeated
   instructions, or five evaluated candidates total (initial + four revisions).
   Only a passing gate exits zero. Keep the best candidate for human review;
   never silently deploy it.

The two runtime paths have different base instructions; the candidate guidance is
appended to both in memory. The original files remain untouched. Safety policies
and source guards remain authoritative. There is no separate held-out set in the
existing five-case suite, so this is a demo gate, **not evidence of generalization
or production readiness**. Optimizer exposure to diagnostics can overfit this set.
Semantic judge failure is distinct from invalid output/operational failure; the
latter fails immediately rather than asking the optimizer to repair credentials.

## Triggers and approvals

Operational HTTP failures expose only allowlisted diagnostic metadata: status,
safe error code, known inference API path, request IDs and referenced Cognitive
Services operation names when supplied by the service. SDK wrapper exceptions
are traversed without logging HTTP bodies, headers, query strings or source
content. A 403 is an operational failure, never a quality verdict; do not broaden
IAM or repeatedly retry inference without reviewing its concrete cause.

Agent source, contracts, shared tools (including the existing ADO MCP
`requirements.txt`), dataset, knowledge, dependency manifest
and this workflow trigger offline checks on PRs and main pushes. PRs, including
forks, never receive Azure credentials. Automatic model execution occurs only on
main with `EVAL_LOOP_ENABLED=true` through the trusted-main-only
`isolated-agent-evaluation` GitHub environment. Manual dispatch on main uses the
same gates. A disabled live job means **quality not evaluated**, not a passing eval.
Superseded runs on the same branch are cancelled. No workflow dispatch is required
to author or test this implementation.

Set `EVAL_LOOP_ENABLED` as a **repository variable**, last, after explicit operator
approval and isolated environment setup. A job-level condition cannot read
environment-scoped variables before admission. Configure the environment separately:

- OIDC variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`;
  a federated credential restricted to this repository/environment, with only
  model inference/evaluation and approved read-only toolbox access. No serving
  agent write, deployment, Teams or wiki-write permission.
- `EVAL_LOOP_CONFIG` containing the JSON below with real reviewed values.
  Use a separate Foundry project and read-only toolbox. This implementation
  provisions nothing and grants no roles. Never use serving21/latest or the
  live gateway. The serving endpoint is a deny target, not an invocation target.
- Exact `main` branch restriction, with no tags and no required per-run reviewer.
  The user approved automatic paid bounded evaluation; source and setup review
  remain required before activation. These settings apply only to the isolated
  evaluation environment; preserve existing release/production protections.
  They are external prerequisites, not created by the YAML.
- Optional `EVAL_LOOP_ARTIFACTS_APPROVED=true` only after reviewing source-data
  publication and repository artifact access. Artifacts can contain model outputs,
  source excerpts and tool results. Retention is three days.

```json
{
  "settings": {
    "DOCUMENTATION_PROJECT_ENDPOINT": "https://ISOLATED.services.ai.azure.com/api/projects/evaluation",
    "TOOLBOX_ENDPOINT": "https://ISOLATED.services.ai.azure.com/api/projects/evaluation/toolboxes/readonly/mcp?api-version=v1",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "reviewed-agent-model",
    "DOCUMENTATION_MODEL_VERSION": "CONCRETE_VERSION",
    "DOCUMENTATION_ADO_PROJECT": "integration-team",
    "DOCUMENTATION_ADO_WIKI": "integration-team.wiki",
    "DOCUMENTATION_AUTH_MODE": "azure_cli"
  },
  "observed_model": "reviewed-agent-model-response-identifier",
  "evaluator_deployment": "reviewed-judge",
  "evaluator_version": "CONCRETE_VERSION",
  "optimizer_deployment": "reviewed-optimizer",
  "optimizer_version": "CONCRETE_VERSION",
  "isolation_review_reference": "operator-reviewed isolation and read-only access evidence",
  "serving_project_endpoint": "https://SERVING.services.ai.azure.com/api/projects/production"
}
```

Local validation (no cloud/model calls):

```bash
python -m pytest tests/release/test_eval_loop.py tests/agents/test_hosted_evaluation.py tests/evals -q
python -m ruff check src/tools/eval_loop.py tests/release/test_eval_loop.py
```

Only after independent approval and Azure CLI login to the isolated identity:

```bash
EVAL_LOOP_APPROVED=true python -m tools.eval_loop \
  --config loop-config.json --output evals/results/isolated-loop \
  --execute-approved-isolated
```

## Bounds and evidence

The workflow has a 55-minute deadline and a 50-minute subprocess termination
bound (forced kill after a further ten seconds). The runner also uses a
50-minute async deadline and 180-second case deadlines; remote judge polling
already submitted can outlive local cancellation. There are at most 25 case executions, 100 agent model
requests, four optimizer calls, ten judge group submissions and 60 case-level
judge results (12 per candidate). Each agent request has a 150,000-byte rendered
input limit and 4,096 output-token cap; optimizer input is limited to 150,000 bytes,
output to 3,000 tokens, and candidate guidance to 12,000 bytes. Tool loops are
limited to eight iterations and twelve function calls per case. Judge jobs use the
existing 20-minute poll deadline. Foundry's managed judge API does not expose an
aggregate token/dollar cap here: configure isolated deployment quotas/budgets
before enabling; request/iteration bounds are not a guaranteed monetary ceiling.
In partial mode the smaller dataset limits execution to 15 case evaluations,
five judge-group submissions and 30 case-level judge results; the same five
candidate and four optimizer-call maximums apply. No live-tool score is invented.

Artifacts contain per-attempt actual execution captures, scores, feedback,
instruction hashes/diffs, parent lineage, final decision, best guidance and a
workflow summary. "Best" means highest minimum normalized judge score, with
status-mismatch candidates ranked zero, but a passing candidate always takes
precedence over every failing candidate; it is not promotion eligibility.
No claimed historical baseline or independently verified CI credentials are supplied.
Future production continuation should consume a separately reviewed immutable
passing candidate; it must not automatically continue to Teams from this demo.

Operational-failure logs and decision files omit arbitrary exception text.
They retain exception class, allowlisted HTTP metadata, and safe validation
types/locations only; validation field names are redacted because dictionary
keys can contain source content. Schema-invalid model outputs remain operational
failures, not quality retries. Restricted execution captures still require the
separate artifact-publication approval.

CI candidate invocation allows one total correction per case, shared between
evidence verification and the SDK's directly wrapped `AnalysisOutput` parsing
failure. A second invalid schema/evidence result blocks evaluation; HTTP,
authentication, timeout, source-integrity and unrelated exceptions do not enter
schema repair. This does not change the serving runtime's repair behavior.
Correction feedback is fixed, not copied from invalid output or exception text.
Each invocation uses a new client, agent, session and evidence/guard context,
resubmitting the canonical input rather than resuming failed conversation state.
Requests set `store:false` and send neither a conversation nor a previous-response
reference. Failed parsing yields no returned response ID or captured output;
this is not a claim about the provider's internal telemetry retention.

Private per-invocation captures retain request-counter deltas and explicit
`schema_invalid`/`failed` status, including failed parse requests in the existing
100-request budget. They never fabricate completed calls or response IDs.
Only the final corrected invocation's complete observed execution is scored;
earlier invocations remain separate evidence, not silently discarded or scored.
Its exact instructions, including the fixed correction when used, are recorded
and hashed in result provenance. All existing judges, thresholds, source checks,
schema constraints and five-candidate limit remain unchanged.

The CLI emits one `eval-loop diagnostics: { ... }` JSON line to stdout on exit,
without publishing raw captures. Version 1 contains only closed stage/reason
codes, exception class, terminal status, validated-suite coverage IDs and integer
counters. It never includes model output, sources, excerpts, instructions,
feedback, exception messages, endpoints or request bodies. Unknown exceptions
retain their class and current stage with reason `unknown`; messages are not
matched against known error text. Explicit local guards use typed operational
errors, for example `case_result / incomplete_execution_or_unexpected_model`
or `evidence_verification / evidence_repair_exhausted`.

Counters are cumulative across candidates, except `attempt_completed_cases`,
which resets when a candidate starts. `attempt_number` is the started candidate;
`completed_candidates` increments only after evaluation and finite-rank
validation. `completed_cases` counts cases whose final result, source checks and
scorer row completed, not merely generated answers. `counted_model_requests`
includes budget-rejected middleware entries; `dispatched_model_requests`
counts SDK dispatch attempts including failed parsing/auth/transport, and
`completed_model_requests` requires a captured response. Neither is a token or
billing count; these model-request counters cover agent calls, with judge and
optimizer calls counted separately. `repair_attempts` increments at the
correction's first SDK dispatch, never inferred from output or instruction content.

Judge group submission counts increment only after the run-create API returns;
completion requires a successful remote terminal run, even if fetching its
outputs later fails. An optional event-only observer in the existing evaluator
supplies those boundaries; other release callers retain its unchanged default
behavior. `judge_results_validated` counts valid case/metric results after local
result-shape validation. Optimizer attempts increment at SDK call dispatch;
completion requires completed status and nonempty guidance. Partial failures
retain their actual counters, without inferring completed candidates or calls.
No diagnostic artifact upload is added; raw publication still requires separate
approval. A hard process kill can prevent the final stdout line.

The CI supplied-source path appends generic contract guidance before the first
invocation and repeats the key checks in its fixed correction guidance. The
serving supplied prompt already requires exact references and verbatim excerpts,
but does not explicitly state `requires_human_review=true` for proposed changes
or every status-dependent array invariant enforced by the Pydantic validators.
Those cross-field validators are not encoded by the generated JSON Schema.
CI guidance spells out those existing rules and the source/URI/version-to-snapshot
copying requirement; it contains no fixture IDs, answers, source pins or per-case
expected statuses. The optimizer sees the same immutable supplied base used by
candidate invocation. Serving prompts, live-tool instructions, schema, source
checks, judges, correction/candidate budgets and thresholds remain unchanged.
This addresses an instruction omission, not proof of the precise offending live
evidence or a claim that a subsequent live evaluation will pass.
