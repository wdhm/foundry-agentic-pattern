# samples/sample-integration/

A **fictional but realistic integration**: the *subject* the Documentation Agent documents. Pull requests that touch `samples/**` trigger the agent ([ADR 0006](../../docs/adr/0006-sources-and-trigger.md)).

> MVP version: a minimal order sync. The planted drift lives in the open demo [PR #62](https://github.com/wdhm/foundry-agentic-pattern/pull/62) (don't merge it); see the [GitHub MCP guide](../../docs/workshop/github-mcp-guide.md).

## Contents
An order sync between two fictional systems: confirmed webshop orders from a Service Bus queue are mapped and posted to the Fabrikam ERP.

```text
sample-integration/
├── src/order_sync.py     # Read message → map → POST to ERP, with retry
└── config/settings.json  # Queue, ERP endpoint, retry policy, mapping defaults
```

PR #62 plants typical drift against the wiki: a changed retry policy (exponential backoff), a new config key (`erp.timeoutSeconds`) and a new dead-letter queue. Infra (Bicep) for the integration is out of MVP scope. The matching ground truth lives in [`data/`](../../data/README.md) and [`evals/`](../../evals/README.md).

All names, systems and data are fictional.

**Owner:** P2 (Knowledge & identity: mock data): Rickard ([@wdhm](https://github.com/wdhm))
