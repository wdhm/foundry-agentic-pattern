# Exact-call Toolbox approval (#15)

**Implementation, not deployed or live-accepted.** Package/approval runtime
version is `0.5.0`; the unchanged assessment implementation continues to report
`0.4.0` in assessment provenance. This is an explicitly
enabled runtime in the existing hosted application, not another dummy-receipt
demo. It consumes an existing Foundry Toolbox through the official SDK and can
dispatch an external call only after a matching native approval. No shared
Toolbox, identity, gateway, wiki, Teams app or Cosmos configuration is changed.

Assessment/evaluation remain read-only. This mode accepts an explicit proposed
write or one selected `AgentResult.proposed_changes` entry, not an `AgentRequest`.
It does not execute proposals automatically, call a model, or prove that a
caller-supplied result/evidence is authentic. The Teams adapter still needs to
carry the selected result and native decisions into this interface. Do not expose
the raw Toolbox connection to that adapter.

## Operator boundary

One reviewed JSON policy pins one versioned Toolbox endpoint, one exact
namespaced tool and all fixed arguments. Only one designated string parameter
(the proposed page content) can vary. Callers cannot choose a tool, endpoint,
project, wiki, page or action in a request. This keeps test writes separate from
the existing read-only assessment path.

Policy fields:

| Field | Required value |
|---|---|
| `toolbox_endpoint` | P2-supplied HTTPS `*.services.ai.azure.com/api/projects/.../toolboxes/.../versions/<number>/mcp?api-version=v1`; no unversioned endpoint |
| `tool_name` | Exact discovered namespaced tool name; do not guess `wiki` versus `wiki_upsert_page` |
| `fixed_arguments` | All target/action/concurrency parameters using the actual discovered schema; restrict to the approved disposable page |
| `content_parameter` | Actual schema property containing the proposed text; cannot also be fixed |
| `proposal_page_parameter` / `proposal_section_parameter` | Optional pair enabling `propose_result`; names of distinct fixed string parameters in a section-aware tool |
| `auth_mode` | `managed_identity` by default; `azure_cli` only for an explicitly authorized local test |
| `timeout_seconds` | Optional, default 60, maximum 180 |
| `approval_ttl_seconds` | Optional, default 3600, maximum 86400 |

The runtime checks the discovered JSON Schema before saving a proposal and
again before dispatch. External schema references and undeclared arguments are
rejected. Task-based tools are not supported. Tool metadata is forwarded through
the SDK MCP session and included in the tool fingerprint. Schema, metadata or
policy changes invalidate existing approvals. There is no fallback to another
tool or schema and no argument dropping.

The `ado___test_write` schema in tests is fictional. **It is not a P2 deployment
configuration.** Fill policy values from Rickard's handoff. Keep the policy in an
ignored local directory until its target has been agreed.

## Start only after the target is agreed

For a deliberately authorized **local** test, place the reviewed policy at
`.azure/approval/policy.json` and authenticate separately. The local entry point
binds only to loopback, requires an explicit execution flag and records the actor
as `local-unverified`; local headers cannot assert an authenticated reviewer.

```powershell
.\.venv\Scripts\python.exe -m documentation_agent.approval `
  --policy .azure\approval\policy.json `
  --state-dir .azure\approval\state `
  --allow-local-tool-execution
```

This entry point is not an offline dummy: **approval can perform a real write**
using the configured identity. Do not run it against the shared wiki merely to
see whether it works. Tests use in-memory MCP call doubles and temporary SDK
storage, without Azure credentials or external network calls. The integration
test also starts an ephemeral loopback MCP HTTP server and stops it on completion.

For a separately coordinated hosted candidate, startup requires both
`DOCUMENTATION_MODE=approval` and `DOCUMENTATION_ENABLE_APPROVAL=true`, plus
`DOCUMENTATION_APPROVAL_POLICY` pointing to a mounted/packaged reviewed policy.
Hosted calls require verified platform user context, the same reviewer and
hosting session that created the proposal, and managed identity for Toolbox.
Do not route the existing assessment endpoint to this mode. No hosted candidate
or serving change is included here.

## Native Responses exchange

### From an assessment result

Send `{"action":"propose_result","result":<full AgentResult>,"proposal_index":0}`
as the JSON string `input` to `/responses`. The index is zero-based and must
select one change; no automatic selection, concatenation or batching occurs.

The adapter validates the full v1 result and evidence references, checks the
selected `target_page` and `target_section` against the policy's fixed arguments,
and copies the selected `proposed_content` exactly. It retains only that change's
referenced evidence. The approval record uses `result.request_id` as `run_id` and
saves the result hash, request ID, selected index, page/section and provenance.
Modify preserves this original-result lineage while generating new arguments
and a new approval; it does not claim that the edited wording was model-generated.

**Section safety:** this direct adapter requires an explicitly configured
section-aware tool. If Rickard supplies only a whole-page upsert API, do not
bind a section fragment as whole-page content. A separate read/compose step with
the current page and concurrency token is required before using the explicit
`propose` input. No page parsing/merging algorithm or tool parameters are guessed.
Whole-page versus section-write semantics remain a P2 handoff decision.

For example, build a request from a saved full result (not the analysis-only
checker file):

```powershell
$result = Get-Content .azure\acceptance-candidate\order-sync-retry-result.json -Raw | ConvertFrom-Json
$command = @{ action = "propose_result"; result = $result; proposal_index = 0 } | ConvertTo-Json -Depth 40 -Compress
$body = @{ input = $command; stream = $false } | ConvertTo-Json -Depth 45 -Compress
# Send $body only to the separately authorized approval endpoint.
```

A valid result and `requires_human_review=true` never count as authorization.
The separate native approval response is still required.

### From explicitly reviewed content

POST `/responses` with one JSON string as `input`:

```json
{
  "action": "propose",
  "run_id": "52f10665-2f45-4f4c-a941-381ce66f08b5",
  "content": "Reviewed replacement text for the disposable test page.",
  "evidence": [
    {
      "id": "example",
      "source": "git",
      "uri": "https://example.com/fictional-source",
      "version": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "excerpt": "Fictional example; replace with the actual proposal evidence."
    }
  ]
}
```

The response contains an inline preview (run ID, pending ID, exact arguments,
SHA-256, expiry and evidence) and an SDK `mcp_approval_request`. Retain its returned
ID and the response ID; do not reconstruct the wire approval ID from preview text.
Always check the response's `status`, not just HTTP 200.

**Approve / Reject:** send a second request using the returned IDs:

```json
{
  "previous_response_id": "<response-id>",
  "stream": false,
  "input": [
    {
      "type": "mcp_approval_response",
      "approval_request_id": "<returned-approval-request-id>",
      "approve": true
    }
  ]
}
```

Use `false` for Reject. Text such as `approve` is not a decision.

**Modify:** use the prior response ID and a JSON string input containing
`{"action":"modify","pending_id":"<pending UUID from preview>","feedback":"Reason","content":"Revised text"}`.
The old call is invalidated before discovering/saving a replacement. The response
contains a new approval request requiring a new decision. A failed replacement
does not reactivate the old call.

**Inspect:** use the same session/response chain and a JSON string input containing
`{"action":"inspect","pending_id":"<pending UUID from preview>"}`.
This returns the stored state, not permission to retry.

## Persistence and failure semantics

The shared approval utilities were extracted from the #1 spike. That spike keeps
its dummy behavior; the new mode uses a different store:
`documentation-tool-approvals-v1`, with SDK user isolation plus explicit owner
and session checks. It records run/call IDs, exact arguments, hashes, supplied
evidence, expiry, decisions, feedback and returned tool result.

### Input/output contract for callers

| Input | Required fields | Successful output |
|---|---|---|
| `propose_result` | Full `result`, integer `proposal_index` | Inline preview + native `mcp_approval_request`; state is `pending` |
| `propose` | `run_id`, `content`, 1-10 evidence entries | Same pending output |
| `modify` | Pending UUID, nonblank `feedback`, replacement `content` | New preview/approval; old state is `modified` |
| `inspect` | Pending UUID | JSON `PendingCall` in one assistant text item |
| Native approval response | Returned approval ID, boolean decision, previous response/session binding | JSON `PendingCall`, `succeeded` or `rejected`; failures are not successful decisions |

Unknown fields are rejected. Text is nonblank and at most 16,000 characters;
feedback is at most 1,000. Full state contains `interface_version=1.0.0`,
`runtime_version=0.5.0`, pending/call/run IDs, status, exact arguments, hashes,
origin (when selected from a result), evidence, owner/session, timestamps and
optional result/decision/replacement fields. Native wire approval IDs are SDK-owned
and may differ from the pending UUID. Generate authoritative schemas offline:

```powershell
.\.venv\Scripts\python.exe -m documentation_agent.approval --print-command-schema
.\.venv\Scripts\python.exe -m documentation_agent.approval --print-state-schema
```

- Local SDK storage uses `AGENTSERVER_STATE_ROOT`. Restart tests reuse that
  directory and session; it is not a multi-instance cloud persistence proof.
- With `FOUNDRY_HOSTING_ENVIRONMENT`, the SDK uses its remote Foundry state
  backend. Its availability, permissions and restart/replica durability must be
  proven on the candidate. Do not set that platform variable manually or mount a
  local directory and call it durable hosted state. Failures propagate; there is
  no application fallback from remote to local storage.
- The SDK store default retention is 30 days. Approval validity is separately
  capped at 24 hours. This store is not the Cosmos audit implementation in #14.
- Store and local response files contain proposal/source data and possibly tool
  results. Keep them out of git; restrict access to the test operator. Do not
  include credentials in tool arguments or policy files.

Before execution, an ETag compare-and-swap changes `pending` to `executing`.
Only the winner may dispatch. The adapter uses the official Toolbox's public MCP
session to issue **one** exact `tools/call`: the higher-level SDK `call_tool`
automatically reconnects/retries after certain connection errors, which is unsafe
for a non-idempotent write. Authentication and platform call-ID forwarding remain
on the official Toolbox transport.

Success is recorded as `succeeded`. Errors, cancellation or timeout after the
claim are non-retryable `outcome_unknown`; a hard crash or storage outage can
leave `executing`. Neither status accepts another decision. Inspect the target
and remote logs before taking further action. **Do not create a replacement
proposal as an automatic recovery step.**

This provides at-most-one dispatch attempt per approval, not an atomic
exactly-once external transaction. A write and the state update cannot be
committed together. External idempotency/concurrency and a reconciliation
procedure are needed for stronger guarantees.

## Runtime acceptance and remaining live integration

The #15 runtime acceptance criterion is that tests prove no approval-gated call
executes without a matching approval. The local integration uses the real
Responses hosting adapter, official FoundryToolbox auth/transport, real MCP
discovery and an ephemeral HTTP MCP server. It exercises a selected AgentResult
proposal through approve/reject/modify, application recreation and competing
decisions. Unit tests additionally cover tampering, expiry, schema/policy drift,
storage failures, cancellation and uncertain outcomes. This is runtime integration
evidence, not proof of Azure identity, the P2 wiki tool or Teams publication.

**P2 (delivered 2026-10-20):** the room chose the simplest path rather than a separate
write identity. Writes reuse the hosted agent identity, the agent user
`documentation-agent@…` (now Basic + Contributors, grant + `wiki.write`) and the
gateway `ca-doc-agent-mcp` (revision `--0000006`, `ADO_MCP_READONLY=false`). The
assessment path still sees only the read tools of `documentation-agent-readonly:1`.
Writes are limited by a dedicated toolbox allowlist plus this runtime:

- Toolbox: `documentation-agent-write`, version 1, exposing only `ado___wiki_upsert_page`
  (`infra/scripts/setup-toolbox.ps1 -Write`).
- Tool: remote ADO MCP `wiki_upsert_page` (`AzureDevOps.Mcp` 1.0.0.0, `X-MCP-Toolsets: wiki`).
  Required `wikiIdentifier`, `path`, `content`, `project`; optional `etag`
  (`string|null`, default `null`) and `branch` (default `wikiMaster`).
  It creates or replaces the **whole page**; it has no section or commit-message parameter.
  With no `etag`, the server reads the current one, so concurrent edits are last-writer-wins (#21).
  Use `propose`, not `propose_result` (the tool is not section-aware).
- Policy: [`approval/sandbox-policy.json`](approval/sandbox-policy.json), packaged at
  `/app/approval/sandbox-policy.json`. Fixed `project=integration-team`,
  `wikiIdentifier=integration-team.wiki`, `path=/Workshop/Approval-Sandbox`,
  `branch=wikiMaster`; `content_parameter=content`; `managed_identity`.
- The parent page must already exist (`/Workshop` was created by an operator). Otherwise
  ADO returns `WikiAncestorPageNotFoundException`, the tool returns `isError`, and the
  record becomes `outcome_unknown`. The runtime logs do not include the tool's error
  text; P1 follow-up.
- Live proof on unserved version `documentation-agent:8`: propose and reject made no
  `tools/call`; approve made exactly one, and the page read back with the approved content.
  Response IDs and ETag are in [setup.md](../../../docs/setup.md#approval-write-path-p2-2026-10-20).

Earlier prompt-agent write permissions are not proof of hosted access.

**P3:** coordinate candidate deployment without changing assessment serving;
verify platform user/session context and remote Foundry state access and durability.
Teams publication and the full Cosmos audit remain separate dependencies.

**P1 live integration checklist:** prove that proposing performs no write; approval
performs the expected one call; reject/modify/tampering/replay do not execute the
old call; pending state survives restart; competing decisions cannot both
dispatch; uncertain outcomes cannot be replayed. Read back the actual target to
verify the effect. These deployment checks and the Teams flow remain outstanding
for #1/#16/#31; completing the #15 runtime does not complete those tickets.

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\agents\test_tool_approval.py tests\agents\test_approval_spike.py -q
```
