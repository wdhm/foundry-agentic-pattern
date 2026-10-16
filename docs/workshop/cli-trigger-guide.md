# Five-minute CLI trigger

The manual fallback for [#10](https://github.com/wdhm/foundry-agentic-pattern/issues/10)
uses the **existing prompt agent `doc-agent`**, not the separately hosted v0
`documentation-agent`. It reads an exact agent version and invokes the Responses
API with `agent_reference`. It never creates/configures agents or changes tools,
instructions, gateway routing or infrastructure. `documentation-prompt` remains
the separate no-tools contract demonstration.

## Install and invoke

Python 3.11+, Azure CLI login (`az login`) and permission to read/invoke the
Foundry project are required. Install in a virtual environment from the repo:

```powershell
python -m pip install -e ".[prompt]"
documentation-trigger invoke --help
```

`python -m tools.cli invoke` is equivalent after installation. Verify the exact
existing prompt-agent version in Foundry and its model version in deployment
configuration. There is no `latest` fallback. On 2026-10-16 the live selection was
`doc-agent:3`, deployment `gpt-6-luna`, model version `2026-09-22`; recheck these
before using a different selection.

For a changed-code assessment, supply an actual full Git commit SHA. This example
uses the pinned demo PR's commit and source references:

```powershell
documentation-trigger invoke `
  --project-endpoint https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic `
  --agent-name doc-agent --agent-version 3 --model-version 2026-09-22 `
  --repo wdhm/foundry-agentic-pattern --commit ad623147fbb1eeb9a6423d437df199c91db15a9e `
  --path samples/sample-integration/config/settings.json `
  --path samples/sample-integration/src/order_sync.py `
  --pr-reference https://github.com/wdhm/foundry-agentic-pattern/pull/62 `
  --wiki-page "/Order Sync/Overview" --work-item 1 `
  --documentation-standard-ref data/documentation-standard.md `
  --requested-by demo-reviewer
```

Replace the paths, wiki page and work item with the sources for your scenario.
`--path`, `--wiki-page`, `--work-item` and `--adr-ref` are repeatable;
`--pr-reference` is optional. `--request-id` and `--correlation-id` accept UUIDs
for external correlation; otherwise fresh UUIDs are generated. A pinned commit
takes precedence over an advanced branch/PR. References identify sources, not
evidence: the agent must retrieve actual content.

## Result and provenance

Stdout is one JSON object with `run_id` (the first real Responses API response
ID), `response_ids` (including continuations), `request_id`, `correlation_id` and
`result` (a schema- and semantics-validated `contracts.v1.AgentResult`).
Extract **`result`** when passing it to a consumer such as the planted-gaps checker;
the whole run report is not an AgentResult. Stderr contains correlation IDs,
response IDs, tool approval details and errors. Exit 0 means a valid assessment,
including an honest `insufficient_information`; invocation, retrieval errors,
refusals or invalid output exit nonzero without a success-shaped result.

The CLI sends request/correlation IDs as Responses metadata and preserves them
locally. It adds provenance from the selected agent's name/version, deployment
name, SHA-256 of the exact instructions and required policy-version metadata.
`--model-version` is a caller assertion from deployment configuration, not a
model-generated value or independently discovered model revision.
Validation checks evidence relationships and version shapes, not source truth
or recall. No telemetry exporter or custom audit store is added.

A read-only smoke invocation on 2026-10-16 against `doc-agent:3` returned a
validated `gaps_found` AgentResult with Git/wiki/work-item evidence.
Run ID: `resp_0c26cb44747c1c09006ad1d8edf2a48194b2b67d734931f75d`;
correlation ID: `e94dcd51-52ca-4d43-8494-9a9eb34cb062`.
This establishes CLI invocation/validation, not eval thresholds or publishing.

## Native approvals and the current P1 boundary

When Foundry emits `mcp_approval_request`, the CLI displays its ID, server, tool
and full arguments on stderr. A human at an interactive terminal must type exactly
**Approve** or **Reject**. It sends `mcp_approval_response` for that exact request
ID with `previous_response_id`, retaining the pinned agent version and correlation
metadata. Rejection sends `approve=false`; the agent may then return an honest
assessment. Multiple requests/rounds are reviewed individually. Invalid input,
EOF, noninteractive stdin or malformed/replayed approval IDs stop without
resuming. There is no auto-approve flag or custom persistence/resume service.

**The current policy is assessment-only.** The CLI checks for the shared
assessment policy, v1 schema, policy metadata and native wiki-write approval
configuration before invoking; it does not relax any of them. The current agent
must return proposals and must not ask to write, even if asked to complete docs.
Do not use a live wiki write to smoke-test this CLI. Approval/rejection/resume
are covered with mocks. A proposed change or `requires_human_review=true` is
not a pending tool call and is never treated as permission to publish.

A full assess -> approve -> wiki-write/Teams flow still depends on P1's
publishing/runtime policy and native HITL integration
([#15](https://github.com/wdhm/foundry-agentic-pattern/issues/15),
[#16](https://github.com/wdhm/foundry-agentic-pattern/issues/16),
[#31](https://github.com/wdhm/foundry-agentic-pattern/issues/31)).
The CLI does not implement that orchestration or convert assessment proposals
into writes. The old hosted v0 stub cannot return this v1 result.

See [ADR 0022](../adr/0022-mvp-scope-platform-first.md) (P3 approved 2026-10-16;
older proposed wording is historical) and
[ADR 0023](../adr/0023-versioned-structured-output-contract.md).
Platform references:
[Responses API and agent_reference](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate#migrate-runs-to-responses),
[native MCP approvals and continuation](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol?pivots=python#create-an-agent-in-python-with-the-mcp-tool).
