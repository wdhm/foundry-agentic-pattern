# Slides: Landing zones and subscription vending (P3, [#50](https://github.com/wdhm/foundry-agentic-pattern/issues/50))

Slot: 11:43-11:50 in the [agenda](../agenda.md), shared with [deployment strategy](deployment-strategy.md). This topic is slides only ([ADR 0014](../../adr/0014-infrastructure-scope.md)); enterprise provisioning and RBAC automation are not built in this MVP.

---

## Slide 1: Vend the guardrails, then deploy the agent

**An AI landing zone is a governed home for the workload, not another agent runtime.**

| Step | Owner | Outcome |
|---|---|---|
| Request | Product team | Owner, environment, data classification, processing boundary, budget and capacity needs |
| Approve and vend | Platform team | Subscription in the right management group; policy, access baseline, network and DNS |
| Deploy and operate | Product team | Foundry, projects, agents and required data services; application access, evals and incident response |

**Shared platform:** connectivity, private DNS, policy and central monitoring standards. **Workload:** model/tool choices, application data and lifecycle within those guardrails.

**Guardrails do not create capacity:** a permitted location or deployment type does not guarantee model availability, quota or PTUs.

> **Speaker notes:** Use the [subscription vending process](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/landing-zone/design-area/subscription-vending) to explain request -> approval -> governed subscription -> workload deployment. Subscription vending is not a resource-group factory and does not automatically install every AI service. An organization can add workload templates as a separate product line. The [Foundry landing-zone reference](https://learn.microsoft.com/azure/architecture/ai-ml/architecture/baseline-microsoft-foundry-landing-zone) separates platform-owned networking, DNS and governance from workload-owned services. Agree on private endpoints, DNS resolution, egress and diagnostic destinations before deploying. Budgets alert; they do not stop spending. These are enterprise next steps, not a claim that this repo vends subscriptions or deploys private networking.

---

## Slide 2: Share for exploration; isolate production deliberately

| Boundary | Good fit | Trade-off |
|---|---|---|
| One Foundry resource, project per team/use case | Exploration with aligned data and trust requirements | Reuse model deployments and network settings; shared operational blast radius |
| Separate Foundry resource per workload boundary | Production, distinct security or lifecycle needs | Independent resource settings and deployments; more provisioning and operations |
| Separate subscriptions for workload/environment boundaries | Delegated ownership, governance and cost management | More platform coordination; still validate service quotas and capacity |

**A project is a workspace/access boundary, not a separate network or capacity pool.**

**For the Documentation Agent:** start from P2's [resource organization](../resource-organization-guide.md); decide production boundaries before adding more teams.

> **Speaker notes:** The [Foundry rollout guidance](https://learn.microsoft.com/azure/foundry/concepts/planning#choose-foundry-resource-topology) recommends isolation by default for production and deliberate colocation for exploration. Projects can separate agents, connections and project-scoped access, but not every API supports project-level isolation. Parent-resource connections can be available to all projects. Validate the exact capability mix and permissions, including the separately governed Search and tool resources. A separate Foundry resource does not automatically provide a separate subscription-level model quota pool. Agree on platform/team ownership and environment boundaries; do not present one topology as mandatory for every customer. No new resources or identities are provisioned by these slides.

---

## References

Technical claims checked against Microsoft Learn on 2026-10-16. Presenter review: confirm the customer's ownership, isolation and residency requirements; P1 assembles these two slides into the shared deck.

- [Subscription vending: process, responsibilities and budget caveats](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/landing-zone/design-area/subscription-vending)
- [Baseline Foundry architecture in an Azure landing zone: resource ownership and subscription setup](https://learn.microsoft.com/azure/architecture/ai-ml/architecture/baseline-microsoft-foundry-landing-zone)
- [Foundry rollout: isolation, resource topology and capability-specific access](https://learn.microsoft.com/azure/foundry/concepts/planning)
