# 0001. Audience is customer architects; the repo is the product, the workshop is the delivery

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0002](0002-workshop-format.md), [0005](0005-generic-repo-with-fictional-data.md)

## Context

Many teams can build a single agent demo. Fewer can build agents *repeatably* with governance, identity, audit, evaluation and release discipline. The people who decide how agents are built in an organisation are architects and technical decision makers. They need something concrete to evaluate, adapt and take back to their teams. A slide deck or a one-off demo is not enough for that.

## Decision

- The primary audience is **customer architects and technical decision makers**.
- **This repository is the product**: a reusable *Agentic Pattern v1* plus one reference agent (Documentation Agent).
- The **workshop is the delivery mechanism**. It walks through the repo, and attendees take the repo home.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Hands-on lab for developers | The audience is decision makers with limited time, and lab setup in customer tenants is fragile |
| Slide-only architecture briefing | Not credible without working code, and nothing to take home |
| Multiple showcase agents | Spreads effort thin; one agent that exercises the full pattern is more convincing |

## Consequences

- **Positive:** a durable asset that outlives the workshop and can be forked and adapted.
- **Negative:** the repo must hold up to scrutiny on its own: docs, ADRs and code quality matter.
- **Follow-ups:** documentation per area is part of the definition of done (M4).
