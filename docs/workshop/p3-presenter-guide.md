# P3 presenter guide: evidence first, live acceptance separate

**Owner:** Louise (P3). **Slot:** 11:10-11:50, 40 minutes, matching the [agenda](agenda.md). **Prepared:** 2026-10-20. John (P1) owns shared-deck assembly. This is source Markdown and a timed fallback plan, not an assembled deck or a completed rehearsal.

**Chosen delivery:** AI Gateway explanatory slides, retained hosted-v6 evidence, and offline evaluation/release walkthroughs. [ADR 0022](../adr/0022-mvp-scope-platform-first.md) permits this gateway fallback. No new cloud/auth/model/tool/session/deployment/routing operation is required or authorized by this guide. Do not dispatch the workflow or improvise a portal change during the talk.

## Run order and hard stops

| Time | Minutes | Material and speaking sequence | Fallback / stop point |
|---|---|---|---|
| 11:10-11:18 | 8 | [AI Gateway slides 1-2](slides/ai-gateway.md): 1 min explain slides-only choice; 3 min distinguish service quota, route limits and attribution; 3 min explain status/counting/cost caveats; 1 min transition | No live 429/403, route enablement or FinOps proof. Use the two tables even if portal access is available |
| 11:18-11:23 | 5 | [AgentOps slide 1](slides/agentops-evidence.md#slide-1-a-deployment-name-is-not-a-version-pin): 2 min identifiers; 2 min revision vs upgrade policy/quota anomaly; 1 min evaluator approval boundary | Use dated inventory, not a new deployment or a claimed durable pin. Embeddings are not the judge |
| 11:23-11:33 | 10 | [AgentOps slides 2-3](slides/agentops-evidence.md#slide-2-one-trace-proves-execution-not-tool-correctness): 4 min retained trace/layer-specific usage; 4 min five-case suite and evaluator coverage; 2 min offline vs live acceptance | Use sanitized trace table if prepared capture is unavailable. No telemetry content export, rerun, guessed judge or invented score |
| 11:33-11:43 | 10 | [AgentOps slide 4](slides/agentops-evidence.md#slide-4-evidence-review-is-not-promotion): 3 min manual workflow/evaluation-only isolation; 3 min version discrepancy and fail-closed behavior; 3 min conceptual routing/rollback sequence; 1 min recap of evidence boundaries | Do not run workflow, create session/version, change selector or time a pretend rollback. Evaluation candidate is never promotion-eligible |
| 11:43-11:46 | 3 | Existing [landing-zone slides 1-2](slides/landing-zones.md): 90 seconds each, ownership/vending then shared vs isolated resources | Slides only; no subscription vending or IaC demonstration |
| 11:46-11:50 | 4 | Existing [deployment-strategy slides 1-2](slides/deployment-strategy.md): 2 minutes each, processing scope then PTU/spillover/regional recovery | Residency is not capacity; routing is not replication. Hand over to shared fork/adapt Q&A at 11:50 |

Total: **8 + 5 + 10 + 10 + 3 + 4 = 40 minutes**. Keep audience questions for the shared 11:50 Q&A. If a view fails, switch immediately to its Markdown table; do not spend the slot diagnosing access. Preserve the final seven minutes for the existing four next-step slides rather than duplicating them.

## Evidence to have ready without making new calls

| Prepared item | Exact allowed interpretation |
|---|---|
| [Model inventory](../setup.md#p3-read-only-inventory-2026-10-16-0757-utc-before-monitoring-approval) | Dated configured chat revision/upgrade policy, IQ embeddings and unresolved `500`/`250` quota report; not live capacity or approved evaluator |
| [Hosted smoke record](hosted-deployment-guide.md#single-approved-assessment-2026-10-19) | One read-only v6/app `0.3.0` assessment, not a five-case gate |
| [Native trace record](../setup.md#hosted-native-trace-evidence-2026-10-20) | Same run, operation `d35d1af1350e3f97df6dd149d69f01ab`; observed model `gpt-6-luna-2026-09-22`; three application chat spans total 19,002 input / 2,715 output tokens |
| Trace tool table | Five successful backend calls: knowledge 1, GitHub 2, wiki 1, work item 1. Nested platform spans and parallel wrapper are not additional usage/backend calls; no argument/schema/tool-accuracy certification |
| [Five-case suite](../../evals/datasets/suite.json) and [evaluation/release guide](evaluation-release-guide.md) | Offline adapter merged in [#87](https://github.com/wdhm/foundry-agentic-pattern/pull/87); live acceptance gated. Not deployed; no approved evaluator/calibration/live good-bad pass |
| [Manual workflow documentation](../../.github/workflows/README.md) and [routing runbook](release-rollback-guide.md) | Explain prerequisites and guards only. Recorded v6 serves 100%; v7 remains unpromoted with session-7/outer-6 discrepancy unresolved |

Use the newer dated setup evidence rather than historical prompt-agent/stub tables in older guides. Code or guide updates do not alter the recorded runtime. Before delivery, Louise and John reconcile any later evidence explicitly; this package does not silently upgrade live-readiness claims when an implementation PR merges.

## Privacy and presentation boundaries

Only present the sanitized facts above or a separately reviewed, already prepared capture. Native telemetry can contain instructions, messages and source/tool content. Do not expand those fields, export raw telemetry/custom dimensions, show local ignored JSON or source-bearing evaluation artifacts, or search message content for caller IDs. Public slides contain no credentials. Layer-specific token usage is not a dollar total.

The talk's unexecuted sequence is **retained serving pin -> isolated evaluation -> evidence review -> separately reviewed assessment rollout -> manual routing verification/rollback**. It is not a request to perform those actions. Local success reports cloud readiness as not checked; source-bearing evaluation versions remain `promotion_eligible=false`. A version mismatch is a stop, not a reason to suppress evidence. Existing sessions do not migrate when routing changes.

## Presenter handoff and outstanding human work

John copies the six primary/fallback slides plus the existing four next-step slides into the shared deck, preserving speaker notes and references. Louise checks wording, pacing, evidence dates and privacy-safe captures; all three presenters review the shared story and rehearse the agenda, including access/visibility and transitions. Visual QA belongs to that assembled deck; no slide render is claimed here.

Keep live evaluator approval/calibration, full five-case good/bad acceptance, routing/rollback proof and the version discrepancy in their owning workstreams. Live wiki approval/Teams delivery is also separate. This material provides honest fallbacks, not acceptance evidence closing [#3](https://github.com/wdhm/foundry-agentic-pattern/issues/3), [#23](https://github.com/wdhm/foundry-agentic-pattern/issues/23), shared-deck [#39](https://github.com/wdhm/foundry-agentic-pattern/issues/39) or rehearsal [#40](https://github.com/wdhm/foundry-agentic-pattern/issues/40).
