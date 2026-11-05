# DEMO / MOCK — AgentOps CI/CD

Real GitHub Actions jobs, synthetic scores, **no deployment**.
This is separate from the existing evaluation and release workflows.
It never imports their code or invokes their paths.

## Run the two scenarios

The workflow is available on the default branch. This simplified revision
must be committed and pushed by an authorized person before it can be used
in GitHub Actions. No push or dispatch was performed for this refinement.

In GitHub: **Actions → DEMO — AgentOps CI/CD → Run workflow**.
Select the branch containing these files, then select:

1. **passing-release**: all jobs turn green; mock serving changes v13 → v21.
2. **blocked-by-groundedness**: Groundedness turns red; the other four
   evaluations pass; the gate turns red; staging, smoke and production skip.
   Mock serving stays v13.

Or, after the workflow is available, from the repository root:

```bash
gh workflow run demo-agentops.yml --repo wdhm/foundry-agentic-pattern \
  --ref main -f scenario=passing-release
gh workflow run demo-agentops.yml --repo wdhm/foundry-agentic-pattern \
  --ref main -f scenario=blocked-by-groundedness
gh run list --repo wdhm/foundry-agentic-pattern --workflow demo-agentops.yml --limit 5
```

Replace `main` only if you intend to run another branch containing the demo.
Run names include the scenario. Open each run's graph and its
**AgentOps quality gate** job summary.

## What to show

```text
Build
  → five parallel Eval jobs
  → AgentOps quality gate
  → Deploy to staging
  → Smoke tests
  → Promote to production
```

- Start with the graph: normal delivery stages surround an AgentOps gate.
- Open Build: source metadata, image digest and candidate identity are prepared
  together. Its summary shows prompt/config, model and evaluation revisions.
- Open the gate summary: candidate/previous versions, version manifest,
  metric scores and per-case scores, then the release decision.
- Compare both scenarios. Groundedness changes from 4.333 to 2.667 against
  a threshold of 4. No other metric changes.
- On success, the production summary explicitly records the mock serving change.
  On failure, the gate explains why mock serving remains unchanged.
- Download the `DEMO-*` artifacts if you want to inspect JSON evidence.
  Evaluation artifacts upload even if their threshold comparison fails.

Job names are kept short for presentation. The gate summary carries one
disclaimer: "Simulation only. No models called or external resources changed."
Other job summaries show only their versions, scores or outcomes.

## Scores and applicability

These are illustrative **DEMO conventions**, not universal Foundry scales.
No Foundry evaluator or model runs here.

| Metric | DEMO scale | Pass at or above | Cases |
|---|---|---|---|
| Wiki claims | 0–1 | 0.9 | Three Wiki cases |
| Wiki accuracy | 0–1 | 0.9 | Three Wiki cases |
| Groundedness | 1–5 | 4 | Three Wiki cases |
| Task adherence | 0–1 | 1 | All five cases |
| Tool-call accuracy | 1–5 | 4 | Two tool cases |

Each metric uses the arithmetic mean of its applicable cases. Every required
metric must pass; there is no average across metrics to hide a failure.
JSON `null` means intentional **N/A** only for the documented inapplicable
combinations. Missing applicable values, extra/missing cases, invalid numbers,
changed candidate identity, malformed evidence, or unsuccessful required jobs
block release. The gate recomputes expected scores from checked-in fixtures.
An evaluation failure is not concealed with `continue-on-error`.

The gate uses `always()` to collect evidence after failed evaluations. That
does **not** authorize release: staging explicitly requires gate success AND
`eligible == 'true'`; production also requires successful smoke tests.

## Versioning and safety

The manifest distinguishes actual source SHA, repository, run ID and attempt
from simulated candidate v21, previous serving v13, image digest, prompt/runtime
revisions, model configuration, dataset and evaluator revisions.
The image digest is syntactically valid but generated for this MOCK story;
no image exists at that reference.

All stages reuse the same manifest. Promotion checks the successful decision
and evaluation evidence again; it does not rebuild or choose another candidate.
Pinning an agent version does **not** freeze an independently managed model
deployment. The recorded model version is release evidence, not an Azure lock.

Only GitHub checkout/artifact operations, deterministic comparisons and summaries
execute. No Azure login, credentials, inference, registry pushes, real tests,
container builds, agent creation, deployment, tags, commits, GitHub Releases,
repository writes, or GitHub Environment configuration. Only `contents: read`
is granted. Artifacts expire after seven days. No customer data is included.
Production approvals could be added to a real pipeline; none occur in this demo.

## Local verification

Python standard library only:

```bash
# From the repository root; tests use temporary directories:
python3 -m unittest discover -s evals/evals_v2/agentops_demo -p 'test_*.py' -v

# If actionlint is installed:
actionlint .github/workflows/demo-agentops.yml
```

Tests execute both scenarios, failed/missing/invalid evidence, threshold
comparisons, Build version summaries, candidate identity and promotion rejection.
They also check the ten-job graph and explicit release conditions. They do not
run application tests or contact external services.
The earlier, granular workflow was verified in hosted runs. The simplified
graph has only been checked locally; hosted verification needs a new dispatch
with permission.

## Files

- [Workflow](../../../.github/workflows/demo-agentops.yml)
- [Deterministic fixtures](fixtures.json)
- [Offline helper](demo.py)
- [Local tests](test_demo.py)
