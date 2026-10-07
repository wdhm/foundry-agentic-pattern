# data/

A **mock data generator** and seed data that make the demo reproducible in any tenant ([ADR 0005](../docs/adr/0005-generic-repo-with-fictional-data.md)).

> Placeholder. Implementation starts in **M2**.

## Planned contents

| Artifact | Seeded into | Notes |
|---|---|---|
| Wiki pages for the sample integration | Azure DevOps wiki + Foundry IQ index | Deliberately incomplete or outdated in places |
| Work items / requirements | Azure DevOps Boards | Linked to the sample integration |
| ADRs for the sample integration | Foundry IQ index | Fictional architecture decisions |
| **Documentation standard** | Foundry IQ index | A **swappable file** that defines required sections, tone and **output language** |
| **Planted gaps + ground truth** | `evals/` | Expected findings per scenario, used by the eval gate |

## Principles
- **Idempotent seeding.** Re-running the generator resets the demo state.
- **Deterministic.** Fixed seeds make eval results comparable between versions.
- **Fictional.** No real customer, system or personal data.

**Owner:** P2 (Knowledge & identity): Rickard ([@wdhm](https://github.com/wdhm))
