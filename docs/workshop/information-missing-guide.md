# Workshop guide: "Information missing" and evidence at exact versions

**Feature:** F4 Output contract · **Owner:** P2 Rickard · **Issue:** [#32](https://github.com/wdhm/foundry-agentic-pattern/issues/32) · **Scope:** MVP ([ADR 0022](../adr/0022-mvp-scope-platform-first.md))

## The result

The agent is asked to fill in facts that **no source contains**: the business owner (DS-10), the Security section (DS-15) and the Operations section (DS-16). It reads every source, then reports what is missing instead of guessing, and pins each piece of evidence to an exact version.

Verified on 2026-10-14: the scenario passed on three runs in a row against `doc-agent-spike:7` (v6 plus the evidence fix under [Gotchas](#gotchas)), and the planted-gaps scenario still passes.

Tool calls: `knowledge/knowledge_base_retrieve`, `ado/wiki`, `ado/wit_work_item` and `github/get_file_contents` (several files at the pinned commit).

Result (shortened):

- `documentation_status: insufficient_information`.
- Proposed content: *"**Business owner:** Information missing: the business owner is not identified in the reviewed sources. Please confirm the accountable business owner before publishing."*
- Missing information: *"DS-10: the business owner is not established. The README's sample Owner entry does not establish business ownership."*
- `requires_human_review: true`.

The README trap is the best demo moment. The sample README has an `Owner:` line for the *code*, and the agent correctly refuses to promote that person to *business* owner.

| Evidence | Source | Exact version | What the agent saw |
|---|---|---|---|
| E1 | wiki `/Order Sync/Overview` | ETag `d897eaf7…` | Purpose and work item #1 only; no owner, Security or Operations |
| E2 / E3 | git `samples/sample-integration` | commit `8a9c9f2a…` | Queue, ERP endpoint, retry, mapping; nothing about identities, classification, logs or runbook |
| E4 | work item 1 | revision `2` | "Fictional sample. Maintain the Order Sync integration…" |

## How it works

No new components. It's the rules that are already in place:

| Piece | Where | What it adds |
|---|---|---|
| Agent instructions | `doc-agent-spike` (set by the setup scripts) | *"If sources or their versions are unavailable, report `missing_information` and `documentation_status=insufficient_information`"* and *"Never invent source content, evidence, versions or findings"* |
| Documentation standard | [`documentation-standard.md`](../../data/knowledge/documentation-standard.md) via Foundry IQ | **DS-22:** write `Information missing:` followed by what is missing. Never guess |
| Output contract | [architecture §4](../architecture.md#4-contract-overview) | `missing_information[]` is the only way to express unknowns; every `evidence[]` item carries a version |

## Evidence at exact versions: how to resolve them

| Source | Version the agent cites | Resolve it | Reference |
|---|---|---|---|
| Git (GitHub) | Full commit SHA | `https://github.com/wdhm/foundry-agentic-pattern/tree/<sha>/samples/sample-integration` | [GitHub MCP guide](github-mcp-guide.md) |
| Azure DevOps wiki | Page **ETag**. This is the git **blob ID** of the page file in the wiki repo, not a commit ID | `az devops invoke --org https://dev.azure.com/foundry-agentic --area git --resource blobs --route-parameters project=integration-team repositoryId=integration-team.wiki sha1=<etag> --api-version 7.1` | [Get Page](https://learn.microsoft.com/rest/api/azure/devops/wiki/pages/get-page?view=azure-devops-rest-7.1), [Get Blob](https://learn.microsoft.com/rest/api/azure/devops/git/blobs/get-blob?view=azure-devops-rest-7.1), [wiki is a git repo](https://learn.microsoft.com/azure/devops/project/wiki/wiki-file-structure) |
| Azure DevOps work item | Revision number | `az devops invoke --org https://dev.azure.com/foundry-agentic --area wit --resource revisions --route-parameters project=integration-team id=1 revisionNumber=2 --api-version 7.1` | [Revisions - Get](https://learn.microsoft.com/rest/api/azure/devops/wit/revisions/get?view=azure-devops-rest-7.1) |

Each version still resolves to the exact content the agent read, even after the page, work item or branch has moved on. That is what makes a later approval or audit trustworthy.

## Run it

```powershell
az login
python evals/check_planted_gaps.py --invoke --scenario evals/datasets/order-sync-information-missing.json
```

The scenario is [`order-sync-information-missing.json`](../../evals/datasets/order-sync-information-missing.json). It passes when:

- the status is `insufficient_information`;
- `missing_information` covers the owner, the data classification and logs/dashboards/runbook;
- every evidence reference resolves, the git evidence is at the pinned commit, and git, wiki and work item evidence are all present;
- **no proposal asserts a value** after `Business owner:`, `classification:` or `runbook:` other than `Information missing`, and no proposal links to a host that isn't a source.

To see it fail, edit a saved result (`--save result.json`) so it says `Business owner: Jane Doe`, then run with `--result result.json`.

## Demo (about 3 minutes)

1. Show the wiki page: it has almost nothing in it.
2. Run the command above, or show a saved result.
3. Point at `insufficient_information`, the `Information missing:` proposals and the README-owner reasoning.
4. Click the commit link, then resolve the wiki ETag and work item revision: the evidence is the exact content the agent read.

## Gotchas

- **Pin the commit in the prompt.** `main` moves with every merge, so the scenario names commit `8a9c9f2a…`. Without a pin, the git evidence version changes from run to run.
- **The standard isn't evidence.** On v6, one run listed the documentation standard (retrieved from Foundry IQ) as `source: git, version: 1.0` with a `blob/main` link. That is not an exact version, and the checker failed the run. The evidence schema only allows `git`, `wiki` and `work_item`, so the model forced it in. [`setup-foundry-iq.ps1`](../../infra/scripts/setup-foundry-iq.ps1) now tells the agent to cite rule IDs in the text and keep the standard out of `evidence[]` (v7).
- **The wiki ETag is a blob ID.** Looking it up as a commit fails (`TF401048`). Use the blobs API, or the items API with the page path.
- **Don't check for names; check for asserted values.** One run mentioned the README owner by name *while* saying the business owner is missing. A plain "name must not appear" check flagged that as fabrication. The checker now matches only a value written after `Business owner:` and similar labels.
- **Wording varies between runs.** The match terms are deliberately broad (`owner`, `classification`, `runbook` plus `log`/`dashboard`).

## Production notes (slides)

- Score "Information missing" behaviour in the eval gate at **100 %** ([ADR 0013](../adr/0013-evaluation-gate-in-ci.md), [evals](../../evals/README.md)).
- Turn `missing_information` into tasks for the owner, such as a work item or a Teams message.
- Check evidence by resolving each version through the APIs above, not only by format.
