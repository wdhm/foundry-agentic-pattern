# Prompt-agent evaluation and release automation

**Offline implementation only, 2026-10-16.** Bounded #25/#26/#27 MVP work;
not completion evidence for #25/#27/#33. P3 approved ADR 0022's platform-first
scope on this date. Five handmade cases, Foundry built-in evaluators, explicit
release criteria, manual promotion and rollback. No custom metric framework,
prompt-agent container build, canary or untrusted-PR execution.

## Dependencies and target

This branch includes dependency commits from open PRs:

| Dependency | Original commit | Purpose |
|---|---|---|
| [#71](https://github.com/wdhm/foundry-agentic-pattern/pull/71) | `5e5e42b3753466b122d6509498b08f93f8921b36` | `tools.cli` assessment parsing and selected-version provenance |
| [#72](https://github.com/wdhm/foundry-agentic-pattern/pull/72) | `a48ab8d58719375ded2db254c20663b5c5e2c219` | dataset/contract v1, five cases and pinned snapshots |

Cherry-picks are separate from the runner implementation commit. Integration
preserves main's hosted runtime type-check scope and latest checker observation
in the dataset README. Merge the dependency PRs first or explicitly reconcile
their equivalent cherry-picks; neither is merged by this package.

Target: **prompt `doc-agent`**, not PR #74's hosted `documentation-agent`.
The no-tools `contracts.prompt` demonstration is unchanged. CLI public behavior,
shared contracts, checker, datasets, P1/P2 runtime policy and infrastructure are
unchanged by the runner. The candidate path conservatively supports only
**appending reviewed instructions**, with all base instructions, model, tools,
structured schema and policy metadata retained verbatim. More extensive policy
or tool changes require a separate reviewed release path.

## What the runner does

`python -m tools.release` takes a local reviewed plan, the existing
`evals/datasets/suite.json`, `EVAL_MODEL_DEPLOYMENT`, a fresh output directory,
and a separate `--execute-approved-cloud` acknowledgement. Without execution
approval it exits blocked; there is no implicit dry-run score or synthetic pass.
Offline verification uses mocked tests, not this execution flag.

1. Validate the five-case suite, contract requests, snapshot blob identities and
   pinned documentation standard. Generate fresh request/correlation IDs per run.
2. Require unexpired approval, exclusive writer hold and evaluator compatibility
   references, a nonempty explicitly selected evaluator deployment, exact
   model-version expectations and all three numeric thresholds.
3. GET the exact named serving agent. Require complete endpoint/identity equality
   with the reviewed snapshot and exactly one concrete version at 100%. Confirm
   active serving/base versions, base still latest, append-only instructions and
   deployment model versions. Recheck approval and serving pin before creation.
4. Create one immutable candidate via `project.agents.create_version`, GET it back,
   require the exact reviewed definition/metadata and active status. Record its
   **actual returned version**, not the base version or application version.
5. Invoke that candidate explicitly with `agent_reference.version`. This deliberately
   **bypasses serving routing**; it is not proof of protected named-endpoint traffic.
   Two live-source cases retain tool execution and verify all pinned reads,
   source content/versions, actual evidence excerpts and Foundry IQ retrieval.
   Unexpected sources or evidence drift block before evaluator submission.
   Three supplied-source cases get only their allowlisted snapshots, with
   `tool_choice="none"`; any returned tool use/discovery blocks.
6. Validate `AnalysisOutput`, assemble caller-owned `AgentResult`, enforce unchanged
   expected status and retain response/run/correlation IDs plus actual provenance.
   Native approvals, tool failures, refusals and incomplete outputs block; the
   unattended runner never approves or resumes a tool request.
7. Submit precomputed outputs to the supported Foundry/OpenAI Evals JSONL
   `file_content` API. Run `builtin.groundedness` and `builtin.task_adherence`
   on all five cases; additionally `builtin.tool_call_accuracy` on the two live
   cases using actual discovered schemas, calls, arguments and tool results.
   Tools-disabled cases are explicitly **not applicable**, not fabricated
   tool-call passes. Both groups are mandatory. There is no score for reference
   answers, no reference-answer leakage into model input, and no baseline comparison.
8. Poll with a bounded timeout, paginate every output row, require all rows and
   evaluator results, completed status, finite in-range scores, passing labels
   when reported, `passed=true`, and every explicitly approved threshold.
   Missing/failed/skipped/incomplete/duplicate results block. Recheck serving
   configuration and model versions, then record `eligible_for_manual_review`.
   **No code path patches routing, promotes, rolls back or deletes candidates.**

Run, candidate and evaluation IDs are persisted as they become available.
`decision.json` starts blocked and only becomes eligible at the very end.
Unexpected SDK/cloud errors propagate nonzero with their traceback; the blocked
decision and already-written diagnostics remain. Interrupted or failed candidates
are retained for manual investigation, never silently cleaned up. A failed
evaluation does not trigger a compensating serving write.

## Release plan contract

Create the plan only after separate live authorization and a coordinated writer
hold. Do not copy current `@latest` into a plan or guess values. The strict
`ReleasePlan` model in `src/tools/release.py` is the canonical schema:

| Field | Required reviewed value |
|---|---|
| `project_endpoint`, `agent_name` | Exact Foundry project URL and prompt-agent name |
| `base_version`, `serving_version` | Positive integer version strings, latest reviewed base and retained serving pin |
| `expected_endpoint`, `expected_identity` | Full `agent_endpoint` and `instance_identity` dictionaries from the approved GET |
| `candidate_definition` | Full exact base prompt definition with only appended instructions; no credentials in committed plans |
| `model_version`, `eval_model_version` | Explicit deployment model versions checked against `project.deployments.get(...).model_version` |
| `thresholds` | All of `groundedness` (1..5), `task_adherence` (0..1), `tool_call_accuracy` (1..5); every case must meet each applicable threshold |
| `approval_reference`, `approved_by` | External authorization record and accountable reviewer |
| `writer_hold_reference` | P1/P2/portal/other writer hold record covering the whole execution |
| `evaluator_compatibility_reference` | Evidence that chosen deployment/evaluator inputs are compatible in this project/region |
| `expires_at` | Future timezone-aware ISO timestamp bounding approval and hold |

No default acceptance threshold or "good baseline" is supplied. Test thresholds
are synthetic fixtures, not recommended production criteria. Review/calibrate
criteria with authorized evidence before enabling cloud execution. The plan's
references are operator attestations, **not a distributed lock or proof of approval**;
the protected GitHub environment and coordination process must enforce them.
Repeated GETs detect drift but are not atomic writes. No ETag/If-Match contract
is assumed. Workflow concurrency serializes this workflow only.

After separate approval, a trusted operator can run:

```powershell
$env:EVAL_MODEL_DEPLOYMENT = "<explicit compatible deployment>"
python -m tools.release --plan "<reviewed-plan.json>" `
  --output "evals/results/<new-run-directory>" --execute-approved-cloud
```

Install the existing `.[prompt,dev]` extras. The command does not provision resources,
change environment settings, configure OIDC, choose a fallback judge or grant roles.
Treat raw tool responses/evaluator inputs as sensitive source data. Artifacts are
ignored by Git under `evals/results/`; review access before uploading them.

## Current live blockers and authorization boundaries

PR [#73](https://github.com/wdhm/foundry-agentic-pattern/pull/73), head
`d299e42633425668703237bca8b7fd0193373f3c`, documents the verified v1 GET/create/selector
contract and manual routing runbook. Its **writer hold remains unconfirmed**;
`doc-agent:3` is active but its named endpoint still follows `@latest`/100%.
It has **not** been pinned. Candidate creation is therefore blocked.

PR [#70](https://github.com/wdhm/foundry-agentic-pattern/pull/70) reports native MI
monitoring already available; do not recreate it. Chat deployment `gpt-6-luna`,
model `2026-09-22`, uses `OnceNewDefaultVersionAvailable`, not a pinned model.
No separate judge deployment or evaluator compatibility has been established,
`EVAL_MODEL_DEPLOYMENT` is unset, and quota 500/250 requires reconciliation.
Model-version pre/post checks cannot prevent mid-run upgrades; coordinate a
model-deployment writer hold too. No configuration/model writes are authorized here.

The OIDC workflow requires later protected-environment/federation/RBAC setup and
an explicit enable switch; see [workflow configuration](../../.github/workflows/README.md).
This implementation authorizes **none** of those changes or a workflow dispatch.
No live inference, candidate creation, endpoint PATCH, promotion, rollback,
publication, Teams delivery or timed rollback demo was performed.

Promotion/rollback remain **manual runbook operations requiring separate approval**.
Review the current PR #73 runbook (or its merged guide) rather than interpreting
an eligible decision as permission to PATCH. Preserve the concrete serving pin,
verify the exact selector and fresh named-endpoint sessions, and coordinate all
writers. No canary support is assumed; the guidance conflicts.

## Offline verification and API references

```powershell
python -m pytest tests/release tests/evals tests/tools tests/contracts -q
python -m ruff check src/tools/release.py src/tools/release_sources.py tests/release
python -m mypy src/tools/release.py src/tools/release_sources.py
```

Mocks demonstrate complete good/bad scores, unchanged serving configuration,
no promotion, no-tools source isolation, missing prerequisites before mutation,
approval/tool failures, live evidence drift and incomplete/skipped evaluation
blocking. These are **mock outcomes**, not baseline or cloud acceptance evidence.

Supported interfaces were checked against installed SDK source and official
documentation, not guessed SDK operations:

- [Cloud evaluation client](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation)
- [Inline JSONL schema, mappings and built-in criteria](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets)
- [Polling, pagination and result fields](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-results)
- [Agent evaluator inputs and scales](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/agent-evaluators)
- [Task adherence SDK example](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/agentic_evaluators/sample_task_adherence.py)
- [Tool call accuracy SDK example](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/agentic_evaluators/sample_tool_call_accuracy.py)
- [Agent endpoint contract](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-agent)

Actual judge compatibility, pass thresholds, cloud result payloads and cost/latency
still require a separately approved live run. This code makes no score, baseline,
live release or rollback claim.
