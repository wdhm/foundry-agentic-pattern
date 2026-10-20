# Slides: AgentOps evidence and release boundaries (P3)

Slots: 11:18-11:43 in the [agenda](../agenda.md). Use the [P3 speaker run order](../p3-presenter-guide.md) for timing and stop points. These slides replay recorded evidence and explain offline implementation; they do not authorize new sessions, model/evaluator calls, deployments or routing.

---

## Slide 1: A deployment name is not a version pin

| Identifier | Recorded fact | What it does not establish |
|---|---|---|
| Chat deployment | `gpt-6-luna`; configured revision `2026-09-22` | A durable pin: upgrade policy was `OnceNewDefaultVersionAvailable` |
| Observed response model | `gpt-6-luna-2026-09-22` on the retained v6 trace | The model for every future call or candidate |
| IQ embeddings | `text-embedding-3-large` | An evaluator chat model |
| Agent / application | Serving agent v6; smoke app `0.3.0` | Model revision or evaluation certification |

**Evaluator selection is still an approval decision:** compatible model/version, capacity, cost and calibrated thresholds. No judge is silently substituted.

> **Speaker notes:** Show the dated [model inventory](../../setup.md#p3-read-only-inventory-2026-10-16-0757-utc-before-monitoring-approval), not a claim of fresh cloud state. Allocation `500` versus reported quota `250` remains unresolved; don't infer spare capacity, a conversion ratio or a fix by reducing chat capacity. A requested model revision and an observed response model are distinct evidence. Pinning the agent does not change the model deployment upgrade policy, and `NoAutoUpgrade` would not prevent eventual retirement. The [model-version guide](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/model-versions) explains those policies. No model/policy/evaluator change is performed here.

---

## Slide 2: One trace proves execution, not tool correctness

**One retained read-only assessment:** hosted v6, app `0.3.0`; observed model `gpt-6-luna-2026-09-22`.

| Application layer | Recorded observation |
|---|---|
| Model calls | 3 chat spans; **19,002 input / 2,715 output tokens** |
| Backend tools | Knowledge 1, GitHub 2, wiki 1, work item 1; all succeeded |
| Correlation | `operation_Id = d35d1af1350e3f97df6dd149d69f01ab` |

**Do not sum nested platform model spans again. Do not count the parallel wrapper as a sixth backend call.**

> **Speaker notes:** The [native trace evidence](../../setup.md#hosted-native-trace-evidence-2026-10-20) was read on October 20 for the same October 19 smoke, not a second execution. Root duration was about 44.4 seconds. Correlate operation, response/session and explicit agent-version attributes; the agent identity GUID is not the version. The complete bounded operation has 1 request, 25 dependencies and 85 traces. These layer-specific tokens are not a full bill. Successful spans do not certify arguments, schemas, output accuracy or `tool_call_accuracy`.
>
> Use only the sanitized table or a previously reviewed content-free capture. Native telemetry can contain instructions, messages and tool content: do not expand/export them or project all custom dimensions. Caller request/correlation IDs were found inside message attributes, not dedicated content-free fields; do not search/display message content to manufacture a structured join. Portal visibility, all-presenter access and evaluation-mode trace ingestion are separate acceptance items. If the prepared view is unavailable, stay with this table; do not run another smoke or add an exporter.

---

## Slide 3: Five cases, three distinct evidence levels

| Suite case | Input design | Question |
|---|---|---|
| Retry behavior | Live pinned sources | Does the finding match the changed implementation? |
| Information missing | Live pinned sources | Does the agent acknowledge an unknown instead of inventing it? |
| Version isolation | Supplied snapshots, tools disabled | Does the historical input stay isolated from current code? |
| Dead-letter stub | Supplied snapshots, tools disabled | Does a stub stay a stub, not a claimed implementation? |
| Wiki unavailable | Supplied snapshots, tools disabled | Does missing wiki remain unavailable rather than trigger a live read? |

**Offline implementation/test pass != local preflight pass != live five-case good/bad acceptance.**

> **Speaker notes:** The unchanged [suite](../../../evals/datasets/suite.json) is the authority. The [evaluation/release guide](../evaluation-release-guide.md) describes the canonical transport/scorer integration merged in [#87](https://github.com/wdhm/foundry-agentic-pattern/pull/87): offline adapter merged; live acceptance gated. That integration is not a deployed evaluation run. P1's opt-in evaluation interface separates live capture from supplied-source isolation. No source envelope is sent to ordinary assessment, and no gold/reference answer becomes model input.
>
> Intended built-in coverage is groundedness and task adherence for all five cases; tool-call accuracy applies only to the two cases with genuinely observed live calls/schemas, not synthetic empty-array passes for supplied cases. Local preflight is `local_preflight_passed`, `cloud_readiness=not_checked`; mocks do not demonstrate judge compatibility. Live evidence still needs an approved compatible evaluator, calibrated thresholds, consistent version binding, complete source/tool evidence and all applicable evaluator results. Missing, duplicate, failed or incomplete evidence blocks. No real passing-good/failing-bad showcase is claimed.

---

## Slide 4: Evidence review is not promotion

| Stage | Safety boundary |
|---|---|
| Prepare | One manual-only workflow; cloud opt-in off by default; reviewed artifact/config, approval and writer hold |
| Evaluate | Isolated source-bearing evaluation candidate; exact session **and** outer execution-version evidence must agree |
| Review | `candidate_purpose=isolated_evaluation_only`, `promotion_eligible=false`, even if evaluation passes |
| Release / rollback | Separate manual approval, ordinary assessment configuration and fresh serving-path proof |

**Recorded serving: v6 at 100%. v7 is unpromoted; session v7 / outer response v6 remains unresolved.**

> **Speaker notes:** Walk through the [release guide](../evaluation-release-guide.md) and [routing runbook](../release-rollback-guide.md) as documents, not commands to run. The manual Action is not automatically dispatched by a merge. Creating an active version is not promoting it; a candidate-specific session bypasses the serving selector and cannot prove named-endpoint routing. Do not relabel evaluation-only configuration as an assessment release or use the unresolved v7 response as candidate proof.
>
> Conceptual routing walkthrough: retain reviewed good version G at 100%, verify state/identity/artifact under a coordinated writer hold, evaluate an isolated candidate, then separately review an ordinary assessment rollout. Only a separately approved routing change may select an eligible assessment version; readback plus a fresh non-overridden named-path session must verify it. Rollback returns the selector to retained G and verifies a new session; it does not move existing sessions, restore conversation state or undo tool writes. No canary, automatic promotion, routing PATCH or timed rollback was performed for this material. Never resolve a mismatch by bypassing the version guard.

---

## References

Recorded facts: [setup evidence](../../setup.md#hosted-native-trace-evidence-2026-10-20) and the linked repository guides. Microsoft Learn references reviewed 2026-10-20 describe capabilities, not completed workshop operations.

- [Model versions and upgrade policies](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/model-versions)
- [Agent tracing: nested execution and captured data](https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept)
- [Dataset evaluation: inputs and evaluator mappings](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets)
- [Hosted agent management and routing](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent)
