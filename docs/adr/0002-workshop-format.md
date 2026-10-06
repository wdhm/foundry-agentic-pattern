# 0002. Demo-driven workshop on a pre-deployed shared environment; attendees take the repo home

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0001](0001-audience-and-delivery.md), [0014](0014-infrastructure-scope.md), [workshop agenda](../workshop/agenda.md)

## Context

The workshop is a half day (09:00–12:00) for architects. Deploying Foundry, AI Search, APIM, Cosmos DB and publishing to Teams live takes too long and depends on permissions in the attendee tenant. Live provisioning is the most common failure mode for this kind of session.

## Decision

- The workshop is **demo-driven** and runs against a **pre-deployed environment in a shared tenant**.
- Attendees **take the repo home** and deploy it in their own tenant with **`azd up`**.
- A backup recording of the end-to-end demo is prepared.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Attendees deploy during the workshop | Slow, permission-dependent and fragile; it takes time from the architecture discussion |
| Deploy into each customer tenant beforehand | Heavy coordination, and access to customer tenants is not guaranteed |
| Recorded demo only | Less credible and does not allow live Q&A against a running system |

## Consequences

- **Positive:** a predictable workshop. Time is spent on architecture and trade-offs.
- **Negative:** `azd up` must work reliably without the presenters' help, which makes M1 and M4 quality critical.
- **Follow-ups:** dry run and demo checklist in M4.
