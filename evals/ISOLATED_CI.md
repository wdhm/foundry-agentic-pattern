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

Agent source, contracts, shared tools (including the existing ADO MCP
`requirements.txt`), dataset, knowledge, dependency manifest
and this workflow trigger offline checks on PRs and main pushes. PRs, including
forks, never receive Azure credentials. Automatic model execution occurs only on
main with `EVAL_LOOP_ENABLED=true` and approval through the protected
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
- Required environment reviewers and main-branch restrictions. These protections
  are external prerequisites, not created by the YAML.
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
