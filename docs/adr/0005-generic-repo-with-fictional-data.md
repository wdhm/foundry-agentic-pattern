# 0005. Generic public repo with fictional sample data; swappable documentation standard

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0001](0001-audience-and-delivery.md), [0006](0006-sources-and-trigger.md), [0019](0019-english-only.md)

## Context

The repo is public and meant to be forked by many organisations. It must not contain customer names, customer data or organisation-specific conventions. The demo still has to feel realistic to enterprise architects.

## Decision

- The repo is **generic**, with no customer or organisation names.
- All integration code, wiki pages, work items and ADRs used as **sample data are fictional but realistic**, and are produced by a **mock data generator** in `data/`.
- The **documentation standard is a swappable file**. It defines the required sections, the rules and the **output language**, so that customers can apply their own standard without code changes.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Use a real open-source project as the subject | Hard to plant controlled gaps; it drifts over time and makes evals unstable |
| Hard-code a documentation standard in prompts | Not adaptable, and it mixes policy with agent logic |

## Consequences

- **Positive:** safe to publish, reproducible demos and easy adaptation.
- **Negative:** the fictional data must be good enough to be convincing, which takes effort in M2.
- **Follow-ups:** a generator with idempotent seeding and deterministic planted gaps.
