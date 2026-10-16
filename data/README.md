# data/

A **small, hand-made fictional data set** ([ADR 0005](../docs/adr/0005-generic-repo-with-fictional-data.md)) that makes the demo story work. There is no generator in the MVP ([ADR 0022](../docs/adr/0022-mvp-scope-platform-first.md)); a generator and seed/reset scripts are on slides ([next steps §9](../docs/next-steps.md#9-production-hardening-out-of-mvp-scope)).

## Contents

| Artifact | Lives in | Notes |
|---|---|---|
| Wiki page `/Order Sync/Overview` ✅ | Azure DevOps wiki (read live by the agent) | Deliberately sparse: purpose and work item #1 only |
| Work item #1 ✅ | Azure DevOps Boards | "Order Sync integration (webshop to ERP)" |
| **Documentation standard** ✅ | Foundry IQ index | [`knowledge/documentation-standard.md`](knowledge/documentation-standard.md): a **swappable file** with rule IDs (`DS-xx`) for required sections, tone and **output language**. Indexed by [`setup-foundry-iq.ps1`](../infra/scripts/setup-foundry-iq.ps1) ([guide](../docs/workshop/foundry-iq-guide.md)) |
| Sample integration ✅ | [`samples/sample-integration/`](../samples/sample-integration/README.md) | Minimal order sync |
| **Planted gaps + ground truth** ✅ | [PR #62](https://github.com/wdhm/foundry-agentic-pattern/pull/62) + [`evals/`](../evals/README.md) | Three drifts (retry/backoff, ERP timeout, dead-letter queue) and the expected findings |
| **Information missing** ✅ | [`evals/`](../evals/README.md) ([guide](../docs/workshop/information-missing-guide.md)) | No source has the business owner (DS-10), data classification (DS-15) or logs/runbook (DS-16); the agent must say so, not guess |

Use your own data instead: see the [bring-your-own guide](../docs/workshop/bring-your-own-guide.md).

## Principles
- **Fictional.** No real customer, system or personal data.
- **Small.** Just enough for one demo story; the wiki and work item were created by hand in [#5](https://github.com/wdhm/foundry-agentic-pattern/issues/5).

**Owner:** P2 (Knowledge & identity): Rickard ([@wdhm](https://github.com/wdhm))
