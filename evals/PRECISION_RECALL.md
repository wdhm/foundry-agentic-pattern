# Precision and recall: real pinned sources

This is the implementation of the **27 October Precision & Recall Eval Flows
brief**, replacing the curated extraction/evidence approach. Start here rather
than `documentation-quality/three-cases.json`: those excerpts and labels are
**unit-test/regression examples only**, not a demo, real agent pages, or calibration.

**Reading map:** `src/tools/precision_recall/` contains `models.py` (handoffs),
`sources.py` (discovery/cache/redaction), `retrieval.py` (local code search),
`llm.py` (one bounded JSON client), `pipeline.py` (both chains and metrics),
`calibration.py` (blind exports/agreement), `foundry.py` (optional publication),
and `__main__.py` (approval/authentication/CLI). The GET-only transport is shared
with `sandbox_eval`, not copied into another runner.

```text
authorized ADO ref metadata -> reviewed immutable commits
  -> complete declared code trees + wiki Markdown + merge diff
  -> heading sections -> extracted atomic claims -> all critical + seeded normal sample
  -> per-claim code retrieval -> independent verifier -> exact citation checks -> precision
  -> fixed engineer facts ---------------------------> full-page verifier -----> recall
  -> restricted paired outputs + coverage + review list
  -> optional source-free Foundry code pass rates (not another judge)
```

## What this evaluates

The page is an **actual pinned `.md` file in the wiki backing Git repository**.
`page.origin` distinguishes `existing_wiki_page` from
`approved_agent_generated_page`; `provenance_reference` records the corresponding
review/output reference. A gap assessment JSON is **not** a page and is never
substituted. The current agent produces assessments/proposals, not approved
published pages, so the first real measurement can evaluate an existing wiki
page only. This is not yet a full agent replay. Neither command can write to
Azure Repos/wiki, change agent policy, deploy models, or grant access.

For each golden case, declare the integration repository at `merge_commit`,
its reviewed `base_commit` for the diff, all related repositories at their own
commits, the page backing repository/commit/path, and engineer-authored
`critical_facts`. Each fact has an exact current-code source line. All code text
files in those declared repositories are discovered and read, not five manually
selected files. Related repos may be in different projects/organizations; each
must be approved for this read identity. Out-of-scope repositories are never
searched. File labels are unambiguous: `repo-id@40-character-commit:/path`.

The reader checks commit/path/blob responses, records source hashes and
inventories, and caches sanitized content by repository coordinates/commit/path
and redaction version. Binary exclusions are explicit. Unsupported submodules,
LFS pointers, incomplete/continuation responses, unsupported changes, unknown
fact sources, missing/empty pages, and file/byte/request limits **stop capture**;
none silently become a smaller source sample. An explicitly declared submodule
pin does not automatically bypass its unsupported tree entry.
Cache/capture hashes detect accidental changes; they are **not signed proof**
against an operator rewriting both content and hashes. Protect local evidence.

Retrieval searches identifiers (backticks, uppercase settings, quoted strings,
numbers/cron) across all declared current code. It includes 20 lines either side
of hits and category-implied config/infra files, then falls back to actual pinned
merge diff/touched files if there are no identifier hits. Old blobs are retained
in the capture for diff audit, never silently mixed into current-code search.
Evidence is bounded to 24,000 UTF-8 bytes by default (roughly 6,000-8,000 tokens
for ordinary code; an estimate, **not an exact tokenizer guarantee**). Truncation,
included files and exact line maps are recorded. The judge cannot cite a line
that was not actually included. Quotes match the sanitized snapshot exactly;
`redacted_citation` identifies quotes containing a redaction marker. Such a line
can establish a setting's name, never its hidden value. Fixed fact source quotes
must likewise use the sanitized line, never paste a secret into a manifest.
Citation presence proves text integrity,
**not entailment**; semantic calibration remains necessary.

## Private configuration and commands

Install the existing extras: `python -m pip install '.[prompt,dev]'`.
Run from the repository root with committed source. Copy
[`precision-recall.manifest.example.json`](precision-recall.manifest.example.json)
and [`precision-recall.config.example.json`](precision-recall.config.example.json)
to a private location and replace every `REPLACE_...` field. These files are
**intentionally invalid/unrunnable**, not fabricated golden cases or model runs.
The CLI validates exact schemas; no branch names are accepted as source pins.

Use the authorization procedure in [SANDBOX.md](SANDBOX.md): a dedicated
approved application identity in CI, or a separately approved personal delegated
login in a dedicated `AZURE_CONFIG_DIR` for manual reads. Delegated mode rejects
CI even with approval flags. Capture and model identities are separate; model
execution never borrows the capture user's token. No personal login is added to
GitHub Actions. Audience/tenant/object/client checks reuse the sandbox guards.

After personally completing the approved interactive sign-in, metadata-only
resolution can establish a real current pin, once:

```bash
# identity.json has {"read_identity": {the approved identity fields}}.
SANDBOX_READ_APPROVED=true python -m tools.precision_recall resolve-pin \
  --identity /private/identity.json \
  --repository https://dev.azure.com/foundry-agentic/integration-team/_git/integration-team \
  --ref refs/heads/main --output /private/code-pin.json --capture-approved-readonly
```

Repeat for the wiki backing repository and each related repository. The command
does not read source at branch tip: it records a ref's commit metadata. Review
and freeze that commit, the actual page path and the diff base in the manifest;
do not invent revisions from the old GitHub fixture examples. Manual delegated
reads additionally require `SANDBOX_MANUAL_USER_APPROVED=true` and
`--manual-user-approved` on resolution/capture.

```bash
python -m tools.precision_recall preflight \
  --manifest /private/manifest.json --config /private/config.json

SANDBOX_READ_APPROVED=true python -m tools.precision_recall capture \
  --manifest /private/manifest.json --config /private/config.json \
  --cache /private/ado-cache --output /private/capture.json --capture-approved-readonly

# Only after approval of these exact sources, models and call/token/time bounds:
EVAL_LOOP_APPROVED=true python -m tools.precision_recall run \
  --manifest /private/manifest.json --config /private/config.json \
  --capture /private/capture.json --cache /private/extraction-cache \
  --output /private/run-001 --execute-approved-isolated
```

Preflight is local validation, not a certificate of authenticated access or
calibration. The isolated Foundry direct endpoint and every model name/version
must be reviewed in config; deployment metadata is checked before/after calls.
The verifier must differ from the candidate by deployment and model/version.
The extractor may share the verifier. Candidate metadata is checked for lineage;
this command does **not** invoke the candidate or generate a page.

Default execution bounds: one concurrent call, 100 total calls **including**
invalid-JSON corrections, 4,096 output tokens per call, 100,000-byte complete
input, 60-second requests and a 1,200-second model-stage deadline. Source bounds
default to 500 discovered items per repository, 600 total GETs, 8 MB sanitized
source, 2 MB per response, and 30 seconds per GET. File limits include folders
and binary entries. Config can lower or raise these only within schema bounds;
review the complete config for approval. One correction is allowed for invalid
JSON/schema/handoff; transport failures, model drift, incomplete responses and
known secrets become stage errors, not scores. SDK retries are disabled.
These limits do not establish a guaranteed dollar cap.

## Outputs and interpretation

Both `precision_results.jsonl` and `recall_results.jsonl` are always produced
after a normal paired execution, including explicit per-item errors. Catastrophic
input/cache/output failures instead produce a source-free `operation_error.json`
and no claimed completion. `precision_recall_summary.json` contains per-page and
micro-aggregated metrics, sampled strata, unjudged counts, page provenance, review
items and an explicit completeness/safety state. The restricted provenance,
call records, extraction/selected-ID files and evidence packets explain each stage.
Zero denominators are `null`, not 100%. Empty extraction/page/facts cannot pass.

Precision is supported / (supported + contradicted) **after citation checks**.
Supported/all-selected, not-verifiable rate and verified/extracted coverage are
separate. This sampled precision is **not an estimate of whole-page precision**.
Recall is stated/all fixed facts, with separate critical recall and wrong counts.
Recall WRONG facts are also reported as precision failures, not silently added
to the sampled precision denominator. Invalid precision citations become
NOT_VERIFIABLE; invalid page quotes become MISSING with review flags. Empty
evidence is valid only for unknown/missing verdicts. Raw critical CONTRADICTED
or WRONG verdicts still yield safety failure even with invalid citations; those
citations cannot suppress the safety signal. Unknown/invalid/unjudged/incomplete
results are never a calibrated pass. No score enables promotion or release.

Repeatability has two parts: canonical claim IDs and seeded sampling reproduce
the selection **for the same canonical extraction**; LLM extraction itself may
vary. Persist/reuse the versioned extraction cache (page, prompt, model and
canonicalization hash) to keep that list fixed. Prompt/model changes invalidate
it. Verification is called afresh, so the <5% verdict-change acceptance criterion
still needs observed repeated real runs. It is not guaranteed by a seed.

## Human calibration, not manufactured labels

Export a blind sheet (no model output/reasons) twice for independent engineers:

```bash
python -m tools.precision_recall export \
  --manifest /private/manifest.json --config /private/config.json \
  --capture /private/capture.json --run /private/run-001 --output /private/blind.csv
python -m tools.precision_recall calibrate \
  --manifest /private/manifest.json --config /private/config.json --run /private/run-001 \
  --reviewer-a /private/engineer-a.csv --reviewer-b /private/engineer-b.csv \
  --output /private/calibration.json
```

Engineers fill `label` and their distinct `reviewer`, leaving inputs/hashes
unchanged. Precision labels: SUPPORTED/CONTRADICTED/NOT_VERIFIABLE; recall:
STATED/WRONG/MISSING. Extraction rows ask engineers to list all atomic claims
in JSON with heading context; the program does not pretend string matching
establishes semantic claim coverage. It computes human/human and judge/consensus
agreement, Cohen's kappa, confusion, contradiction sensitivity and disagreements
with model reasons. Degenerate/empty kappa stays null. Input hashes must match
the actual judge inputs. Threshold/sample observations are reported; **release
gates remain disabled even if a partial calibration target is observed**.

For retrieval/extraction coverage, `coverage-review --adjudications /private/review.json`
(with the same manifest/config/output arguments) scores explicit
human-adjudicated records. Retrieval records contain `stage="retrieval"`,
`origin="human_adjudication"`, `review_reference`, `input_sha256`, `needed_files`
and `retrieved_files`. Extraction records use `stage="extract"` and `human_claims`
with `severity` and an explicitly adjudicated boolean `matched`. These imports
are human evidence, not automatically verified labels. Never use unit-test
records as real evidence.

Required targets remain: one live exact-content read per repo; 50 supported
retrieval examples with >=95% needed-file coverage; 10 extraction docs with no
critical misses and >=90% all-claim coverage; 150 precision claims with human
and judge kappa >=0.8 and >=90% contradiction sensitivity; 50 recall fact/page
pairs with kappa >=0.8; and three hand-checked real golden cases. Engineers must
resolve disagreements and version prompts/guides, then repeat against the same
inputs. Retain sensitive sheets in restricted storage, **not a public repo**.
Production fact selection and the optional HTTP evaluator remain deferred.

## Actions and Foundry

The existing `agent-evaluation-loop.yml` now has a separately selected
`precision-recall` job after offline validation. Dispatch `pipeline=precision_recall`
only after configuring reviewed `PRECISION_RECALL_MANIFEST`,
`PRECISION_RECALL_CONFIG`, `PRECISION_RECALL_ENABLED=true` **and**
`EVAL_LOOP_ENABLED=true`, with protected `main` and the existing
`isolated-agent-evaluation` environment approval/OIDC identity. Both source/model
application identities must equal this job's one approved identity. PRs receive
no credentials; pushes never auto-run the paired path. Offline test/lint/types
include the new code. No variables, identities, resources or access are enabled
by this change.

There is **no existing replay or report-and-gate job** to insert between.
Instead, real capture, paired scoring and a source-free report are honest named
steps in the new job. No fake replay success or new page is claimed. Incomplete
operations fail the job; critical semantic failures remain visible in restricted
results without introducing uncalibrated release gates.

Foundry publication requires the additional dispatch checkbox
`publish_precomputed` and `PRECISION_RECALL_PUBLICATION_APPROVED=true`:

```bash
PRECISION_RECALL_PUBLICATION_APPROVED=true python -m tools.precision_recall publish \
  --manifest /private/manifest.json --config /private/config.json \
  --run /private/run-001 --output /private/foundry-001 --run-id reviewed-run-001 \
  --publish-approved-sanitized
```

It uses the actual SDK catalog `code_text` evaluator and inline JSONL dataset
API described in [Microsoft's custom evaluator documentation](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/custom-evaluators).
Runs are named `precomputed-precision-<run-id>` and
`precomputed-recall-<run-id>`. These are **code pass rates of precomputed local
verdicts**, never a new independent model verdict or calibration. Only hashed
case/target IDs, severity, effective verdict, completion/citation flags and a
constant source-free reason are submitted. Claims, facts, quotes, evidence,
prompts and model reasons remain local. Per-row reasons in Foundry are therefore
explicitly limited; raw-detail publication is not implemented/authorized.
Catalog/run creation is a separate cloud write, never implicit in local scoring.

Source-bearing artifact upload additionally needs both
`EVAL_LOOP_ARTIFACTS_APPROVED=true` and `PRECISION_RECALL_ARTIFACTS_APPROVED=true`.
It is disabled by default; review repository visibility/access before enabling.
Ignored `evals/results/<new-name>` or external private output directories are
required, existing outputs are not overwritten, and POSIX modes are 0700/0600
where supported. Restrict Windows ACLs separately. Known credential markers
are redacted/blocked before model exposure, caching or output; this heuristic
is **not a secret-free guarantee**. Approve bounded source exposure and review
source-bearing data independently before sharing it anywhere.

## Current operational boundary

Implementation/tests are not live/calibrated acceptance. The known source
target is `foundry-agentic/integration-team`, repository `integration-team`,
wiki `integration-team.wiki`, logical page `/Order Sync/Overview`. Its backing
Git filename, actual commits/base/related repos and engineer facts must be
established by authorized reads, not guessed. The [existing sandbox access
blocker](SANDBOX.md#manual-capture-with-sashas-own-login) still applies: Sasha
personally signs in to the dedicated tenant/cache; Basic membership alone
does not prove repository Read ACLs. CI's UAMI is not established as onboarded
to those ADO repos. No login, IAM change, paid run or publication was performed
for this implementation. Once authorized input is captured and bounded model
execution approved, observe both chains, review real labels, then separately
approve Foundry submission. End-to-end acceptance remains blocked until those
events and calibration actually occur.
