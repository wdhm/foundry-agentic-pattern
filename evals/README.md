# evals/

**Primary runtime update (2026-10-16):** hosted `documentation-agent`, per
ADR 0024 and P3's confirmed target. The unchanged five-case dataset below is
not proof of hosted runtime compatibility. Ordinary assessment accepts bare
`AgentRequest` and does not export nested tool-call/schema evidence.
**Main update, 2026-10-19:** P1's separate disabled-by-default evaluation interface
supports isolated supplied sources and observed execution records; see
[the canonical interface](../src/agents/documentation-agent/EVALUATION_INTERFACE.md).
**Adapter update, 2026-10-20:** the P3 hosted runner now integrates that canonical
envelope and maps observed model calls, policy results and discovered schemas to
built-in evaluators. All five cases are exercised offline, including real P1
framework capture with deterministic model/tool doubles. No isolated evaluation
deployment, live evaluator scores or tracing ingestion is certified.
The [release preflight](../docs/workshop/evaluation-release-guide.md)
requires explicit isolated config, reviewed task scopes, evaluator identity/version/
thresholds and fresh serving pin/proof/writer hold. Evaluation blocks conflicting
or absent outer/session version evidence; no override is available.
It never sends gold answers to the model
or drops required cases. The checker's existing `--invoke` path below remains
**prompt compatibility/diagnostics**, not hosted release certification.

**MVP: five hand-made cases, existing checker and built-in evaluator adapter; live gate outstanding.**
P3 approved the platform-first scope on 2026-10-16
([ADR 0022](../docs/adr/0022-mvp-scope-platform-first.md)).
This package prepares data for [#24](https://github.com/wdhm/foundry-agentic-pattern/issues/24);
the evaluator/release workflow in #25/#27 is separate. No custom metric framework,
live agent configuration or tool writes are added by the adapter. A passing
evaluation version is evidence-review-only, never eligible for ordinary serving.

## Dataset entrypoint

Load [`datasets/suite.json`](datasets/suite.json), version **1.0.0**. It indexes
**five cases total**, including the two existing reusable scenarios:

| Case | Distinct purpose | Expected status | Inputs |
|---|---|---|---|
| `order-sync-retry` | All three planted wiki gaps: retry/backoff, ERP timeout, dead-letter queue | `gaps_found` | PR #62 code/config + sparse wiki |
| `order-sync-information-missing` | Owner/classification/operations unknowns; code owner is not business owner | `insufficient_information` | Historical code/config/README + wiki + work item |
| `order-sync-version-isolation` | Do not import newer PR facts into an older configuration | `insufficient_information` | Historical config only; wiki deliberately absent |
| `order-sync-dead-letter-stub` | A queue name/docstring does not prove delivery; implementation only prints | `insufficient_information` | PR #62 code/config only |
| `order-sync-wiki-unavailable` | Paired negative control for the drift case: no wiki, no proven wiki gaps | `insufficient_information` | Same PR code/config; wiki deliberately unavailable |

There is no invented "up to date" case: the fixtures do not contain a complete,
verified integration page. These cases are a small workshop sample, not a
representative benchmark. Expected answers are editorial ground truth, **not
agent responses or observed scores**.

### Stable interface (JSON, UTF-8)

Paths below are relative to `evals/datasets`, except the standard's repository-relative
`path`. Consumers must select cases through `suite.json`, **not glob every JSON file**
(the directory also contains the suite and source envelopes).

| Field | Shape / meaning |
|---|---|
| `dataset_version` | Semantic version for this data interface; bump for incompatible changes |
| `contract_version` | `1.0.0`; explicit imports from `contracts.v1`, not the hosted v0 contract |
| `documentation_standard` | Repository `path`, pinned `commit_sha`, `git_blob_sha`, `role=rules_only` |
| `sources[]` | Unique `id`, contract `source`, HTTPS `uri`, exact `version`, `snapshot` path, nullable `git_blob_sha`, `availability=snapshot`, scope/provenance `note` |
| `cases[].id` / `scenario_file` | Stable case ID and the compatible existing-checker scenario file |
| `cases[].request` | Complete contract-v1 `AgentRequest`, validated by the existing Pydantic model and committed JSON Schema |
| `cases[].input_mode` | `live_sources` for the original tool demos; `supplied_sources` for controlled source bundles with tools disabled |
| `cases[].source_ids` | Allowlist of source records for this case only; never supply the whole catalog |
| `cases[].rationale` / `reference_answer` / `forbidden_claims` | Human-authored purpose, expected answer text and semantic negative expectations; evaluator reference material, never model input |
| `cases[].integration_blockers` | Case-specific remaining dependencies/risks; empty is not a claim that a runtime exists |
| `cases[].baseline` | `state` (`historical_report_only` or `not_run`), nullable documentary `reference`, factual `observations`; no synthetic scores |

Scenario files preserve `scenario`, `agent`, `prompt`, `expected_status`,
`planted_gaps`/`expected_missing`, and `expected_evidence`. Each expectation has
`id`, `title`, `rules` and `match_all` groups. The two original files are unchanged;
their legacy `subject`/`context` fields remain, while `cases[].request` is the
canonical v1 request. The information-missing legacy `subject.paths` is represented
by `request.subject.changed_paths`. Stable request/correlation UUIDs identify rows;
an execution adapter may replace both for each run, retaining the case ID separately.

## What was actually checked

On **2026-10-16**, preparation read the Git objects at
`8a9c9f2acff643ed15a41e6b43f2f8eb18502b4f` (historical config, code, README),
`ad623147fbb1eeb9a6423d437df199c91db15a9e` (PR #62 head config/code), and
`2dd57c18bb0589e85c556ddbc032bce688d059f5` (standard).
Bundled Git snapshots are exact file content, with blob identities in the catalog.
Fixtures are **source text, not executable sample modules**.

Read-only Azure DevOps REST retrieval also succeeded:

| Source snapshot | Exact version | Checked content / scope |
|---|---|---|
| [`order-sync-wiki.json`](datasets/fixtures/order-sync-wiki.json) | ETag `d897eaf7cd02c4da6bd70df5cae951ba6790df9f` | Full page: purpose and work-item link; no planted technical details or required owner/security/operations facts. ETag is a Git **blob** ID, not a commit. |
| [`order-sync-work-item.json`](datasets/fixtures/order-sync-work-item.json) | Item `1`, revision `2` | Title, description, type and state; complete returned field-name inventory. Identity/timestamp/process metadata values omitted deliberately. This is a scoped documentary snapshot, not a full REST response or evidence of work-item history/comments. |

The full ETag matches the prefix in the historical guide. The sources support
the retained expectations within this documented scope; no new fixtures were
invented to make the agent pass. Git/wiki blob hashes are checked offline, with
LF normalization for checkout line endings. Work-item identity/revision and
snapshot scope are checked, but its content has **no server-supplied hash**;
offline checks cannot independently authenticate that REST capture.

## Running the existing checks offline

Use the repository's existing Python environment (`.[dev]` and Python 3.11+):

```powershell
python -m pytest tests/evals tests/contracts
python -m contracts.generate_schema --check
python evals/check_planted_gaps.py --scenario evals/datasets/order-sync-retry.json --result saved-result.json
```

The checker CLI validates saved `--result` payloads as `contracts.v1.AnalysisOutput`
(model fields). For an `AgentResult` caller envelope, validate it separately and pass
only its analysis fields to the checker. An envelope must echo the
request ID and carry real caller-supplied runtime provenance. Never fill provenance
from reference answers. Proposed changes require human review, not write approval.

## Local code-based baseline from hosted captures

`documentation-code-eval` (or `python -m tools.code_eval`) complements the
existing diagnostic checker and Foundry model-judged evaluators. It runs **only
local Python checks** against the existing five-case suite and saved hosted
evaluation captures; there is no invocation, credential discovery, judge/API
call, deployment, approval renewal or promotion path.

From the repository checkout, with Python 3.11+ and the existing
`.[agent,prompt,dev]` environment:

```powershell
python -m tools.code_eval `
  --captures evals/results/candidate-run `
  --plan evals/results/reviewed-plan.json `
  --output evals/results/baseline.json
```

Input is the **unmodified** `CASE_ID-evaluation.json` files saved by
`tools.hosted_release`, one for every case indexed by `datasets/suite.json`,
plus that run's saved hosted evaluation plan. Each capture contains outer
session/artifact lineage and `evaluation: {result: AgentResult, execution:
ExecutionRecord}`. The plan provides the reviewed artifact, definition,
model version, observed model, serving label and task scopes; it is not
reconstructed from answers. Bare `AnalysisOutput`, ordinary assessment results,
legacy prompt traces and a prior baseline are **not** supported inputs.
Missing/malformed required captures fail; unexpected case filenames are an
input error. Duplicate JSON keys and repeated execution/session/request/model
response identities fail, rather than overwriting or skipping cases.

The default output is the ignored `evals/results/baseline.json`. It is a UTF-8
JSON array in suite order, with exactly `{score, result}` per case. `score`
contains `case_id`, the booleans below, `passed`, nullable `error`,
`evidence_kind`, and SHA-256 digests of the parsed suite and full saved plan
(sorted-key JSON). `result` retains the entire input capture, including source,
commit, model, prompt, policy and transport lineage; it is `null` when the
evaluation contract cannot be parsed. Valid-contract captures are retained
even when another check fails. Required failures use `false`, not a skip,
inapplicable score or perfect fallback.

| Check | Exact meaning and applicability |
|---|---|
| `contract_valid` | The nested `EvaluationResponse`, including `AgentResult`/execution, validates through the shared contracts. Includes evidence-ID uniqueness/reference resolution, status structure and human-review requirements. Does not imply capture completeness. |
| `status_matches` | Exact equality with the scenario's structured `expected_status`. Four cases require `insufficient_information` and a contract-valid nonempty missing-information explanation; this checks structural abstention, not whether its prose is correct or complete. |
| `source_consistent` | Existing source verifier accepts evidence kind/URI/exact version/excerpt against case fixtures, with HTML unescaping and whitespace normalization. For two live-source cases, captured reads must also cover required sources and match pinned readable content; supplied-source cases must not contain observed MCP operations. |
| `execution_valid` | Existing capture and evaluator-input validators accept request/task correlation, packaged instructions/provenance, isolated bundle, completed model calls, final-answer assembly and observed tool/schema/result linkage under the read-only policy. Also checks saved outer/session/artifact lineage and independent case identities. For three supplied-source cases tools must be absent; two live-source cases require actual captured read calls/schemas. This is a deterministic boundary check, **not** Foundry tool-call accuracy. |
| `passed` | All four checks are true and no input/duplicate error exists. There is no weighted aggregate or semantic accuracy score. |

Exit **0** means all five cases passed; **1** means at least one required case
failed (the full five-row report is still written); **2** means configuration,
suite or I/O failure (diagnostic on stderr, no new report; any old report is
unchanged). Reports are published by same-directory temporary file and atomic
replacement; failed writes/replacements clean up the temporary file. Always
check the exit code before consuming an existing file.
The optional `--suite` uses the same versioned five-case loader, not a new
corpus format. Paths can be overridden with `--output`; it cannot overwrite
the plan, suite or captures.

These checks deliberately do **not** score editorial answer/forbidden-claim
keywords as semantic groundedness, business-owner correctness, stub-fidelity
reasoning or missing-information completeness. A vacuous/no-claim response can
have source-consistent citations and still be unhelpful. Saved captures are
untrusted evidence: consistency checks cannot authenticate that a model/tool
actually ran, restore unavailable snapshots, prove current access, validate
blocked integrations, or certify a serving version. The committed wiki blob
and scoped work-item revision are reused as documented above; the work-item
projection is not a complete independently authenticated REST capture.
Existing suite blockers/baseline classifications are unchanged. Replay does
not enforce fresh live-write approval/serving-proof timestamps because it
never invokes or writes to the service.

No measured five-case agent baseline is bundled. Tests reuse the existing
synthetic capture doubles and exercise success/failure/exit behavior with
network, credential, live-execution and judge entrypoints blocked. Use
`--evidence-kind synthetic` for such grader tests; the default `saved_capture`
labels replayed evidence, **not** newly measured/live quality. Do not commit
private captures, plans or generated reports. The three existing Foundry
evaluators remain separate: groundedness (minimum 3/5), task adherence
(exactly 1), and tool-call accuracy (minimum 3/5; only the two live-tool cases).

### Existing live and saved-response diagnostic checker

[`check_planted_gaps.py`](check_planted_gaps.py) uses shared Pydantic contract
validation, documentation status, recall, evidence integrity and the existing
proposal fabrication guard. Live/raw-response checks also match evidence to
actual source reads.

```powershell
az login
.\.venv\Scripts\python.exe -m pip install -e ".[prompt,dev]"
.\.venv\Scripts\python.exe evals\check_planted_gaps.py --invoke --agent-version 3
.\.venv\Scripts\python.exe evals\check_planted_gaps.py --invoke --agent-version 3 `
  --scenario evals\datasets\order-sync-information-missing.json
.\.venv\Scripts\python.exe evals\check_planted_gaps.py --result my-result.json
```

Use `--save-response evals/results/response.json` with `--invoke` to preserve the
tool evidence locally; use `--response` to recheck it without another model call.
Raw responses may contain source data; do not commit them. A bare saved `--result`
does not provide source-read verification. Explicit `--agent-version` avoids
silently evaluating a newer deployment.

**Latest observation (2026-10-16):** `doc-agent:3` passed both scenarios with 100%
recall, schema validation and source-read evidence checks. This version adds
scoped assessment instructions and explicit precedence for missing facts.
See the [gap-analysis guide](../docs/workshop/gap-analysis-guide.md) for the
failed version 2 attempt, limitations and reproduction commands.

The checker remains a lightweight diagnostic: status, keyword recall,
reference resolution, allowed Git versions, required source kinds and the original
proposal fabrication patterns. Each `match_all` group must match in the same item.
Its exit code is nonzero on failure. The CLI validates the analysis contract;
`--invoke` and `--response` additionally match evidence source, URI, exact version
and verbatim excerpt against observed read-tool outputs, require standard retrieval
and reject detected write calls. A bare `--result` cannot verify source reads.
These checks do not independently authenticate saved traces or enforce the suite's
exact wiki/work-item gold versions, and do not evaluate every semantic negative
expectation. Passing is not a built-in evaluator result or release gate.
The focused dataset tests use synthetic unit-test outputs only, not baseline runs.

## Handoff to the built-in evaluator/release workflow

1. Join each case with its scenario, standard and **only its allowlisted sources**.
   Model input is the scenario `prompt`, validated `request`, rule text and source
   metadata/content. Keep expectations, reference answers and baseline records out
   of model input. For Git snapshots supply the full file text; for wiki use
   `content`; for work items supply the documented `fields` projection and scope.
2. For `supplied_sources`, disable tools and preserve absent wiki/work-item sources.
   This isolates version contamination, stub fidelity and unavailable evidence.
   Do not run these prompts with the checker's `--invoke`: it neither supplies the
   bundles nor disables tools, even when `--agent-version` is specified.
3. For `live_sources`, retrieve exact Git versions, wiki blob and work-item revision
   read-only, and compare with the captured versions before scoring. Auth/access may
   differ per execution. If the wiki has moved, use its pinned blob or explicitly
   version/update the dataset; do not score new content against stale gold. The
   snapshots also permit a deliberately labelled replay of the scoped source text;
   replay is not a live tool-call evaluation.
4. A later runner must support grounded/tool-enabled v1 assessment and offline
   source injection, assemble/validate `AgentResult`, check correlation, and record
   real agent/model/prompt/policy versions. `contracts.prompt.validate_response`
   deliberately supports only the **no-source/no-tools** contract demo and rejects
   grounded findings; it is not this runner. Do not weaken it or patch shared agent
   instructions to fit this dataset.
5. Select compatible Foundry built-in evaluators (groundedness, task adherence,
   tool-call accuracy where actual tool traces exist), their input mappings, model
   deployment and release criteria in #25/#27. The observed chat deployment is not
   proof of evaluator compatibility, and there is no assumed separate eval
   deployment. Do not create a cost-incurring deployment without that decision.
   No tool-call accuracy score should be invented for offline replay.

All five cases have the documentary inputs needed for offline preparation. Live
readiness still depends on authorized retrieval, a verified exact current agent
version, the later runner and compatible evaluator deployment. This package makes
no new agent baseline claim. The historical status-precedence failure remains
visible alongside main's later version-3 observation; future runs must measure
their selected version, not silently change gold.

## Baseline, not targets

The pre-existing README and
[information-missing guide](../docs/workshop/information-missing-guide.md) report
2026-10-14 runs against `doc-agent-spike:7`: both original scenarios PASS, information
missing three consecutive times. Against `doc-agent:1`, planted gaps PASS and
information missing **2 of 3** PASS; the failure found all missing items but selected
`gaps_found` instead of `insufficient_information`. Raw outputs and full runtime
provenance were not committed. These are historical checker observations, **not**
new built-in evaluator scores. Main subsequently recorded `doc-agent:3` passing
both original scenarios on 2026-10-16 with schema and source-read verification
(see [gap-analysis guide](../docs/workshop/gap-analysis-guide.md)). This later
observation does not overwrite the dataset's historical baseline records or
constitute a five-case baseline. The three added cases have **not been run**.

[ADR 0013](../docs/adr/0013-evaluation-gate-in-ci.md) describes the longer-term
blocking gate (schema validity, recall target, zero fabricated references and
information-missing correctness). No recall target, evaluator threshold, CI gate
or automatic promotion/rollback is implemented by this dataset package.

**Owner:** P3 (AgentOps & platform): Louise ([@llandinl](https://github.com/llandinl))

## Isolated CI demo

See [isolated evaluation and improvement CI](ISOLATED_CI.md) for the separate
five-candidate GitHub Actions demo. Offline checks do not assert changed-agent
quality; real evaluation requires an explicitly approved isolated environment.
