# Hosted approval spike (#1): native protocol, dummy write

**Status: local runtime portion implemented; Teams go/no-go is still pending.**
This is an isolated experiment, not the production approval workflow in #15.
The assessment app remains read-only and unchanged.

## What it proves locally

The spike emits Agent Framework `function_approval_request` content. The official
`ResponsesHostServer` maps it to a native `mcp_approval_request`. A client sends
`mcp_approval_response` with an approval ID and a boolean decision. The host loads
the original call; the spike verifies the call, arguments hash, owner and session
before accepting a decision.

The only target is **`dummy.write`**, whose entire effect is a stored receipt.
It does not call a model, a Toolbox endpoint, Teams, GitHub or the wiki.
This establishes the native transport and local replay guard; it does **not**
prove that Toolbox approval metadata is enforced or that Teams renders it.

| Decision | Effect |
|---|---|
| Approve | Atomically changes pending to approved and stores one dummy receipt containing the exact approved arguments |
| Reject | Marks rejected; no receipt, and later approval fails |
| Modify | Marks the original modified; creates a different proposal and hash which needs fresh approval |
| Duplicate, stale or tampered | Fails explicitly; no new receipt |

Pending data, argument hash, run ID, owner, session and decision use the SDK's
`FoundryStateStore`. The local SDK backend persists files beneath an explicit
state directory. A conditional ETag write commits decision and dummy receipt
together, so old response snapshots cannot reset a decision. No Cosmos DB or
new application database is introduced.

Evidence, exact versions, proposed text and argument hash are included in the
message body, not only native citations. Sample evidence is fictional and
clearly labelled as not independently verified.

## Run locally

From the repo root, using the installed `agent` dependencies:

```powershell
.\.venv\Scripts\python.exe -m documentation_agent.approval_spike `
  --port 8090 --state-dir .azure\approval-spike-local
```

This local-only entry point binds to `127.0.0.1`. Its reviewer is deliberately
recorded as `local-unverified`, never as an authenticated Teams user. The state
directory is git-ignored and should not be shared. Stop with Ctrl+C.

In a second PowerShell terminal:

```powershell
$endpoint = "http://127.0.0.1:8090/responses"
$proposal = Get-Content .\src\agents\documentation-agent\examples\approval-proposal.json -Raw
$pending = Invoke-RestMethod -Method Post -Uri $endpoint -ContentType application/json `
  -Body (@{ input = $proposal; stream = $false } | ConvertTo-Json -Depth 20)
$approval = $pending.output | Where-Object type -eq "mcp_approval_request"
$preview = ($pending.output | Where-Object type -eq "message").content[0].text
$preview

# Approve the exact saved call. Use $false to reject instead.
$decision = @{
  previous_response_id = $pending.id
  stream = $false
  input = @(@{
    type = "mcp_approval_response"
    approval_request_id = $approval.id
    approve = $true
  })
}
$result = Invoke-RestMethod -Method Post -Uri $endpoint -ContentType application/json `
  -Body ($decision | ConvertTo-Json -Depth 20)
$result
```

Check `status`, not just HTTP 200: the hosting adapter reports execution failures
in a `status: failed` envelope. Sending the same decision again must fail.

**Modify a still-pending proposal instead of approving it:**

```powershell
$pendingId = (($preview -split "\n") | Where-Object { $_ -like "Pending ID:*" }) -replace "^Pending ID: ", ""
$modify = @{
  action = "modify"
  pending_id = $pendingId
  feedback = "Use the revised wording."
  content = "Revised fictional proposal."
}
$revised = Invoke-RestMethod -Method Post -Uri $endpoint -ContentType application/json `
  -Body (@{
    previous_response_id = $pending.id
    stream = $false
    input = ($modify | ConvertTo-Json -Compress)
  } | ConvertTo-Json -Depth 20)
$revised
```

Approve/reject using the new approval ID and `$revised.id`. Modify is an explicit
spike command, not a built-in third boolean decision or a verified Teams button.
There is no automatic model regeneration in this deterministic experiment.

## Findings (2026-10-16)

Local SDK and HTTP exercises demonstrated approve/reject/modify, persistence
across agent recreation, matching arguments, session/owner checks, stale ETags,
competing decisions and replay rejection even from the original response ID.
No external write was performed. The temporary HTTP server was stopped.

The SDK's native approval store loads saved approvals; loading does not consume
them. Consequently, native transport alone is not our replay guarantee. The
separate versioned proposal record rejects reused or superseded decisions.

**Limitations**

- Exactly one stored dummy receipt is not a proof of exactly-once external wiki
  writes. A real side effect needs an idempotency/recovery strategy in #15.
- Modify invalidates the old record before creating the replacement. If creation
  fails, the old call stays invalid; recovery is deliberately not automated.
- A native storage precondition failure is handled explicitly. Other storage
  errors propagate; there is no success-shaped fallback.
- The local SDK persistence backend is not evidence of cloud storage durability
  or multi-instance correctness. Verify that separately in Foundry.
- The server class requires platform user context unless explicitly constructed
  for the loopback demo. Local headers/request text cannot establish a verified
  reviewer. Actual channel identity propagation remains unverified.
- No Toolbox tool was created or connected. No Teams publishing, UI screenshot
  or native approval-card behaviour has been verified.

## Remaining #1 work and ownership

1. **P1/P2:** agree on a real dummy Toolbox tool with approval metadata; keep it
   isolated from the real wiki. P1 must enforce approval before dispatch.
2. **P3 #4 / P1:** deploy the spike and publish with Teams "Just you" scope after
   reviewing platform user identity and storage configuration.
3. **P1:** demonstrate all decisions in Teams, verify inline evidence and replay
   rejection, and capture screenshots. If Teams cannot carry native approvals,
   record that evidence and evaluate the agreed CLI fallback.

No Teams **go** or **no-go** decision is justified by the local proof alone.
The ticket stays open until the channel experiment is complete.

References:
[Foundry publishing](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot)
and [MCP approval concepts](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol).
