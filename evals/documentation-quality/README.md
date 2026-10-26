# Local documentation-quality thin slice

This is an **offline, no-remote-write demonstrator**, separate from assessment
status evaluation and release certification. It makes no cloud, inference or
Foundry calls, submits no runs, publishes nothing, and changes no serving prompts,
request/source guards, workflows, retries, thresholds or release gates.

`three-cases.json` contains **synthetic, manually curated technical excerpts**,
atomic claim spans and candidate critical facts. They are not historical agent
replays, generated-agent captures, human-approved truth or measured calibration.
The first-stage scope uses only existing compatible cases:

| Document | Existing case | Why compatible |
|---|---|---|
| `retry-draft` | `order-sync-retry` | Configuration excerpt at the PR head; intentionally incomplete coverage of retry/backoff/queue facts |
| `version-draft` | `order-sync-version-isolation` | Historical configuration excerpt; no later defaults or unseen wiki assertions |
| `stub-draft` | `order-sync-dead-letter-stub` | Distinguishes the configured queue name from the print-only implementation |

The owner/classification/operations case and wiki-unavailable case are not
converted into invented complete documents. No unavailable snapshots or previous
agent outputs have been reconstructed. All selected cases retain their original
per-case source allowlists in `evals/datasets/suite.json`. Here even the original
live-source retry case is read from pinned local fixtures, **not executed**.

## Run locally

Use the repository's Python 3.11+ development environment (editable package and
dev dependencies, as for the existing evaluation tools), from the repository root:

```powershell
python evals\documentation_quality.py measure
```

This prints a sanitized JSON summary only. With no imported labels, semantic
values are `null`, with `incomplete` status and explicit unjudged counts. It
does **not** assign unsupported, missing, zero, or pass to unjudged items.

To collect real reviewer labels, explicitly create a restricted local directory:

```powershell
New-Item -ItemType Directory -Force evals\documentation-quality\private
python evals\documentation_quality.py export --output evals\documentation-quality\private\review-packet.json
```

The ignored `private/` directory and existing ignored `evals/results/` directory
are the intended destinations for raw material. Export is opt-in and refuses
to overwrite any existing file. Files use owner-only permissions on POSIX;
**on Windows, set a user-only directory ACL yourself before exporting**. Git
ignore is not access control. Do not commit or publish reviewer names, labels,
source material, packets or raw judge responses.
Exports inside the checkout are restricted to these two ignored directories.
An explicitly chosen path outside the checkout is also accepted; its directory
privacy and lifecycle remain the caller's responsibility.

The packet contains the dataset, rubric, exact evidence excerpts, pinned source
catalog (snapshot paths relative to `evals/datasets/`), per-case allowlists and
an unlabeled `labels` object. Review full allowlisted fixtures, not just the
selected excerpts. Only those fixtures may establish facts; the documentation
standard is rules-only. Review claim atomicity and completeness, critical-fact
selection, and applicability before labeling. Curated critical facts are
candidate annotations, not an authoritative exhaustive fact inventory.

Copy **only the `labels` object** to a separate JSON file. Set `origin` to
`human` or `external_judge`, fill `producer` and `producer_version` with the
reviewer/annotation revision or judge/model/prompt configuration reference, and
fill the rows. This tool neither runs nor fabricates a judge. Supply externally
obtained results manually; it provides no inference integration.

```powershell
python evals\documentation_quality.py measure --labels evals\documentation-quality\private\judge.json
python evals\documentation_quality.py calibrate --judge evals\documentation-quality\private\judge.json --human evals\documentation-quality\private\human.json
```

`--dataset PATH` before the command permits a reviewed revision of the same
three selected cases and three-document shape, not an unbounded benchmark. `schema_version`,
`dataset_version`, evaluator/rubric versions, pinned standard commit/blob and
the combined dataset/suite digest are recorded. Labels with mismatched
provenance, duplicate/unknown identities or invalid verdicts are input errors.
The summary retains label-content and producer/version hashes rather than raw
reviewer metadata. It excludes document text, evidence, source URLs and local
paths. Do not treat this as a general-purpose redactor for arbitrary input.

## Label and metric contract

Rows join deterministically on `(case_id, kind, target_id)`, never text matching
or row order. A document has one `document` target using its document ID;
claims and facts have their own ID namespaces within that document.

| Kind | Applicable labels | Meaning |
|---|---|---|
| `document` | `pass`, `fail` | Useful, factual technical excerpt with honest limitations and review notice; not a full wiki acceptance decision |
| `claim` | `supported`, `contradicted`, `unverifiable` | Semantic relation to this case's pinned evidence only; lack of evidence is not contradiction |
| `fact` | `covered`, `missing` | Whether the critical fact is conveyed by the draft, including faithful paraphrases |

`null` or an omitted row means **unjudged**, not a skip or negative label.
`skip` is permitted only for a dataset-inapplicable target with its exact
`skip_reason`. For example, historical settings cannot establish runtime
timeout defaults without implementation evidence. Such targets are excluded
from denominators and reported explicitly. They must not be labeled covered.

Every numeric metric includes numerator, denominator, value and status:

| Metric | Definition |
|---|---|
| `supported_all_claims` | supported / all applicable claims |
| `supported_decidable_claims` | supported / (supported + contradicted); never substitute this for the all-claims rate |
| `contradiction_rate` | contradicted / all applicable claims |
| `unverifiable_rate` | unverifiable / all applicable claims |
| `critical_recall` | covered / applicable critical facts |

The claim taxonomy is exhaustive for labeled applicable claims. If any applicable
claim is unjudged, **all four claim rates remain null/incomplete**. Recall is
likewise incomplete until all applicable facts are labeled. Once complete, an
empty denominator yields `null` with `empty_denominator`, never zero or one.
An empty claim/fact set therefore cannot manufacture a perfect score.

The `overall` block micro-aggregates numerator and denominator counts across
documents **before dividing**, never averages document rates. It includes all
five metrics above, observed `contradiction_count`, summed per-kind coverage,
case-qualified inapplicable targets and deterministic check pass/fail/skip
counts. If any document has unjudged applicable claims (or facts), the
corresponding overall claim rates (or recall) remain null/incomplete.
Contradiction counts include only labeled contradictions; when coverage is
incomplete they are not a claim about the unjudged targets. Empty denominators
retain the same explicit semantics at the overall level.

Calibration reports per-kind paired count, unpaired coverage, observed agreement,
the full confusion matrix (**rows=human, columns=judge**) and unweighted Cohen's
kappa. Kappa uses marginal expected agreement; no pairs yields null, and expected
agreement of one yields null/`degenerate`. Contradiction sensitivity is
judge-contradicted / human-contradicted among paired claim labels; no human
contradictions yields an explicit empty denominator. Partial calibration uses
only paired applicable labels and reports what is excluded; it is not complete
calibration. Judge and human label provenance is retained by hash.

**No genuine owner labels are bundled.** Regression tests explicitly use
`synthetic_regression` provenance; their agreement/kappa results are arithmetic
tests, not evidence of judge reliability. Even genuine labels on these three
curated excerpts cannot establish deployment readiness or representative quality.
Calibration and measurement never enable a semantic gate.

## Deterministic checks and limits

The loader reuses the existing pinned-suite loader and contract validation. It
checks fixture Git blobs, standard provenance, exact citation excerpts, per-case
allowlists, unique joins and claim spans. Citation integrity does **not** prove
that an excerpt entails a claim; imported semantic labels do that.

Checks report proposal-only declared action and the explicit human-review
marker (`DQ-*` local policy), the DS-22 missing-information marker when required,
and a narrow DS-23 known-credential-marker scan. They do not prove actual
runtime read-only behavior, English fluency, absence of PII/secrets, source
completeness or semantic accuracy. DS-10 through DS-17 full-page layout is
explicitly skipped because these are technical excerpts, not full integration
pages. No marketing/tone heuristic is misrepresented as a semantic judge.

Exit **0** means evaluation completed, even when quality labels/checks fail;
exit **2** means operational/input error, with no score-shaped result. The CLI
keeps raw exception payloads out of stderr; use the Python loader and validators
in a restricted local debugger to inspect detailed validation failures. It does
not catch operational errors and turn them into zero scores.

Focused verification:

```powershell
python -m pytest tests\evals\test_documentation_quality.py tests\evals\test_datasets.py -q
ruff check evals\documentation_quality.py tests\evals\test_documentation_quality.py
$env:MYPYPATH = "src"
mypy --follow-imports=silent evals\documentation_quality.py
```

On Windows/WSL network checkouts, SQLite-backed mypy caches can report
`database is locked`; use `--cache-dir` pointing to a user-only local Windows
directory rather than changing repository tooling or suppressing type errors.
