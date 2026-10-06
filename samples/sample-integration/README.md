# samples/sample-integration/

A **fictional but realistic integration**: the *subject* the Documentation Agent documents. Pull requests that touch `samples/**` trigger the agent ([ADR 0006](../../docs/adr/0006-sources-and-trigger.md)).

> Placeholder. Content arrives in **M2**.

## Planned contents
A small, self-contained integration that is typical of enterprise integration landscapes, for example an order-sync service between two fictional systems:

```text
sample-integration/
├── src/          # Integration code (e.g. an Azure Function that maps and forwards messages)
├── infra/        # IaC for the integration (Bicep), e.g. Service Bus, Function App, Key Vault refs
└── config/       # Environment config, mappings, schedules, retry policies
```

The sample is designed so that typical documentation drift can be **planted** on purpose: a new endpoint, a changed retry policy, a new config key or a removed dependency. The matching ground truth lives in [`data/`](../../data/README.md) and [`evals/`](../../evals/README.md).

All names, systems and data are fictional.

**Owner:** P2 (Knowledge & identity: mock data)
