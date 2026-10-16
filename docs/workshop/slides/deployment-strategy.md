# Slides: Model deployment strategy (P3, [#51](https://github.com/wdhm/foundry-agentic-pattern/issues/51))

Slot: 11:43-11:50 in the [agenda](../agenda.md), shared with [landing zones](landing-zones.md). This topic is slides only ([ADR 0014](../../adr/0014-infrastructure-scope.md)); PTU, spillover, multiregion routing and full APIM FinOps are not built capabilities in this MVP.

---

## Slide 1: Choose the processing boundary before the capacity model

**For Azure OpenAI model deployments, scope and billing are separate choices.**

| Standard deployment | Where inference can run | Decision |
|---|---|---|
| Standard | Within the customer-specified Azure geography | Use when that geography boundary is required and supported |
| Global Standard | Across Azure regions globally | Use when global processing is acceptable |
| Data Zone Standard | Within the Microsoft-defined data zone | Use when that zone meets the data-processing requirement |

**Then choose capacity:** pay-per-token Standard types for variable demand; supported Provisioned types (PTU) for reserved processing capacity and lower latency variance.

**Neither a resource region nor a processing boundary guarantees model availability, spare capacity or end-to-end failover.**

> **Speaker notes:** The [deployment-type reference](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/deployment-types) distinguishes processing location from data at rest. Standard is geography-scoped in the current guidance, not a promise to process only in the resource's individual region. Data Zone is a Microsoft-defined boundary, not a customer-selected list of regions. Check its current definition against the customer's policy. Stored data has separate residency commitments; also review logs, tools and connected stores. An Azure Policy allowed-location rule alone does not constrain inference to that region: review deployment types too. These choices do not apply unchanged to all partner or managed-compute models. Before presenting, check the exact model/version, deployment type, resource region, quota and deployable capacity. No fixed price or model/region availability is promised here.

---

## Slide 2: Separate burst handling from regional recovery

| Mechanism | What it adds | What you must still design |
|---|---|---|
| PTU + native spillover | Baseline reserved capacity; eligible failures/overage sent to a Standard target | Supported pair in the same Foundry resource, matching model/version and approved processing scope; target quota and token charges |
| APIM AI Gateway backend pool | Round-robin or weighted distribution; priority groups and circuit breakers | Compatible backends, failure rules, bounded retries, access and routing only to approved locations |
| Separate regional endpoints | An alternative endpoint when a resource region is unavailable | Pre-deployed capacity, a resilient gateway/network, agent/tool/data dependencies and tested recovery |

**Routing is not replication. Residency is not a capacity guarantee.**

> **Speaker notes:** [Native spillover](https://learn.microsoft.com/azure/foundry/openai/how-to/spillover-traffic-management) is configured explicitly, not enabled merely by buying PTUs. It prefers the provisioned deployment and can add latency; Standard fallback can also fail and is billed separately by token usage. Verify supported deployment pairings and keep fallback within the same approved processing boundary. Spillover inside one resource is not a separate-region recovery design.
>
> [APIM backend pools](https://learn.microsoft.com/azure/api-management/backends#load-balanced-pool) distribute requests across configured endpoints. Priority routing uses lower-priority groups only when higher-priority backends have tripped circuit breakers. Load balancing and breaker decisions are approximate across gateway instances; this is not an exact traffic split or capacity reservation. Validate tier support (backend circuit breakers are not supported in Consumption), handle `429`/`Retry-After`, and avoid unbounded retries or replaying side-effecting agent tools.
>
> Global/Data Zone model routing does not remove the resource-region outage concern. The [resiliency guide](https://learn.microsoft.com/azure/foundry/how-to/high-availability-resiliency) requires customer-designed failover and dependency recovery. Model endpoint failover does not move conversations, indexes or approvals. Pin and evaluate compatible model versions on each route, load-test fallback, and rehearse failure and failback before claiming resilience. These are future design options, not the workshop's manual agent-version rollback demo.

---

## References

Technical claims checked against Microsoft Learn on 2026-10-16. Presenter review: recheck current model/type/region support, spillover eligibility, data-zone definitions and APIM tier before delivery; P1 assembles these two slides into the shared deck.

- [Model deployment types: processing locations, Standard and Provisioned choices](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/deployment-types)
- [Native spillover: prerequisites, failure behavior and billing](https://learn.microsoft.com/azure/foundry/openai/how-to/spillover-traffic-management)
- [APIM backends: load-balanced pools and circuit breakers](https://learn.microsoft.com/azure/api-management/backends)
- [Foundry high availability and resiliency: customer-managed recovery](https://learn.microsoft.com/azure/foundry/how-to/high-availability-resiliency)
