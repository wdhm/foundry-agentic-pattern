# data/

A **mock data generator** and seed data that make the demo reproducible in any tenant ([ADR 0005](../docs/adr/0005-generic-repo-with-fictional-data.md)).

> Placeholder. Implementation starts in **M2**.

## Planned contents

| Artifact | Seeded into | Notes |
|---|---|---|
| Wiki pages for the sample integration | Azure DevOps wiki (read live by the agent) | Deliberately incomplete or outdated in places |
| Work items / requirements | Azure DevOps Boards | Linked to the sample integration |
| ADRs for the sample integration | Foundry IQ index (later) | Fictional architecture decisions |
| **Documentation standard** ✅ | Foundry IQ index | [`knowledge/documentation-standard.md`](knowledge/documentation-standard.md): a **swappable file** with rule IDs (`DS-xx`) for required sections, tone and **output language**. Indexed by [`setup-foundry-iq.ps1`](../infra/scripts/setup-foundry-iq.ps1) ([guide](../docs/workshop/foundry-iq-guide.md)) |
| **Planted gaps + ground truth** | `evals/` | Expected findings per scenario, used by the eval gate |

## Principles
- **Idempotent seeding.** Re-running the generator resets the demo state.
- **Deterministic.** Fixed seeds make eval results comparable between versions.
- **Fictional.** No real customer, system or personal data.

**Owner:** P2 (Knowledge & identity): Rickard ([@wdhm](https://github.com/wdhm))
