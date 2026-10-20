# Slides: AI Gateway fallback (P3)

Slot: 11:10-11:18 in the [agenda](../agenda.md). **Disposition: explanatory slides**, as permitted by [ADR 0022](../../adr/0022-mvp-scope-platform-first.md). No gateway enablement, traffic change, load test or live FinOps/429 proof is part of this presentation. Follow the [P3 speaker run order](../p3-presenter-guide.md).

---

## Slide 1: Three controls, three different questions

| Control | Question it answers | Boundary |
|---|---|---|
| Model service quota/allocation | How much rate-limit allocation may this subscription assign? | Region + model + deployment type; not a project budget |
| AI Gateway token limits | How much may callers consume through this project/model route? | Project-scoped model deployment TPM and token quota |
| Cost attribution | Which team, agent and version caused the spend? | Trusted identity/version correlation + usage + billing reconciliation |

**A gateway limit does not increase service quota, reserve model capacity or prove per-agent cost.**

> **Speaker notes:** Walk across the table rather than opening the portal. The [Foundry limits guide](https://learn.microsoft.com/azure/foundry/control-plane/how-to-enforce-limits-models) configures limits for a model deployment within a project. Do not call these native per-agent/version limits. A custom APIM counter key is a separate policy design requiring trusted identity and tested traffic routing. Foundry's gateway uses APIM, but no evidence here establishes that the recorded hosted smoke traversed it. Keep the existing AI Search embeddings deployment distinct from the chat and evaluator decisions. The [recorded quota anomaly](../../setup.md#p3-read-only-inventory-2026-10-16-0757-utc-before-monitoring-approval) is an allocation-review blocker, not permission to resize a working deployment.

---

## Slide 2: Token controls are not a cost ledger

| Documented behavior | What we can say today |
|---|---|
| TPM rate limit exceeded: `429`; token quota exhausted: `403` | Expected gateway policy behavior, **not observed live here** |
| Concurrent/streaming requests can affect token counting | A configured ceiling is not an exact billing cap |
| Usage needs model/version and rate context | Token totals alone are not an invoice or per-agent chargeback |

**Next step, not MVP delivery:** verified route coverage and identity/version attribution, privacy-reviewed telemetry, then reconciliation with actual billing.

> **Speaker notes:** The [APIM token-limit reference](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy) distinguishes rate from period quota, warns about temporary overshoot under concurrency, and describes streaming estimates and independent gateway counters. A `429` may also originate from the model service; status alone does not identify the enforcing layer. Don't generate throttling to illustrate this slide. Explain that model tokens, cache/rate differences, gateway/runtime and connected-service costs require separate accounting. We have a native usage observation, not a validated FinOps ledger, hard dollar cap or live gateway demo. Full APIM FinOps remains deferred; no configuration is proposed or applied during the talk.

---

## References

Microsoft Learn behavior reviewed 2026-10-20; these are product capabilities, not workshop execution evidence.

- [Configure Foundry AI Gateway: resource association and project enablement](https://learn.microsoft.com/azure/foundry/configuration/enable-ai-api-management-gateway-portal)
- [Enforce token limits for models: project/deployment scope and status codes](https://learn.microsoft.com/azure/foundry/control-plane/how-to-enforce-limits-models)
- [APIM token-limit policy: counters, estimates and concurrency](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy)
- [Azure OpenAI quota allocation](https://learn.microsoft.com/azure/foundry/openai/how-to/quota)
