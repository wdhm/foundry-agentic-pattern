# Teams approval cards (#16)

**Teams adapter in package 0.6.0.** The earlier published v8 was a
Responses-only approval runtime; its Foundry channel bridge displayed the text
preview, not an interactive approval card. This implementation adds native
Activity handling in the same application, using
`azure-ai-agentserver-activity==1.0.0b4` and the M365 Agents SDK. It follows the
official [Activity echo sample](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/bring-your-own/activity/echo)
and SDK multi-protocol host composition. No separate bot service is added.
That deployment used approval runtime 0.5.0. The new conditional-page extension
uses runtime 0.6.0 in package 0.8.0 and is not yet deployed. Package, approval-engine and Foundry deployment versions
are different identifiers; deployment evidence must record the immutable image.

**Deployment recorded 2026-10-20:** this working-tree snapshot was built as
`documentation-agent:13` and selected at 100% with user approval. Image digest:
`sha256:7ee0d68538a08a41e53e1575261fcc7fbd696d5bff18e0c96c6cce153b5e1345`.
The v13 startup/Responses proposal smoke passed without approval or a wiki write;
the test session was stopped. The existing tenant publication and Bot identity
were preserved, and v8 retained. Subsequent real Teams checks are recorded below.
The deployment initially included uncommitted changes; exact source hashes are recorded
locally under ignored `.azure/teams-card-deployment/`, and the handoff is on #16.

## What the card does

The optional [merged-PR draft flow](PUSH_FLOW.md#merged-pr-draft-review-new-code-not-live-enabled)
uses a compact card with a commit-pinned Azure Repos draft link instead of inline
content/evidence. Notification follows a completed PR, not an open PR. The
runtime verifies the published draft bytes before notifying the reviewer;
Approve uses those same saved bytes. This new mode is not enabled on the current
deployment. Explicit/manual proposals retain the full card described below.
With `compose_wiki_page`, the draft is the complete updated integration page
and **Changes** links to separate diff/evidence notes; it is not the sandbox report.

One card shows the exact tool name, all fixed arguments, full proposed content,
supplied evidence with exact versions, expiry and run/pending/hash identifiers.
Text uses Adaptive Cards `RichTextBlock`/`TextRun`, so proposal Markdown is not
interpreted as links or formatting that could obscure the approved content.
Teams controls typography, colors, contrast, focus and light/dark theme.

- **Approve:** the server reconstructs the native decision from the persisted
  call, never from client-supplied tool arguments. The existing #15 claim/hash/
  expiry/policy checks still apply before dispatch.
- **Reject:** the existing runtime records rejection; no tool call.
- **Modify:** opens a separate card with labeled replacement-content and feedback
  inputs. **New proposal** invalidates the old proposal and creates a new
  approval; it never approves the edit. **Cancel edit** returns to the unchanged
  proposal.
- **Refresh status:** appears on terminal/expired cards. An uncertain outcome
  never becomes a retry action.

Cards use `Action.Submit` with a message/value callback. This is a deliberate
choice rather than `Action.Execute`: an approved external call can exceed Teams'
short invoke-response deadline. We do not acknowledge success before the runtime
has recorded it or start an untracked background write. Repeated deliveries
remain protected by the runtime's atomic pending-call claim.

Each action sends a new result card. Previously delivered cards can remain
visible; stale buttons are rejected server-side. Use `show <pending-id>` to
retrieve current state. No optimistic success, automatic write retry or silent
fallback is implemented.

## Identity and conversation boundary

Only personal Teams chats in `DOCUMENTATION_TEAMS_TENANT_ID` are accepted.
Group chats and channels are intentionally rejected in this first version.
Organization-wide catalog visibility does not change this personal-chat rule.

The Activity SDK supplies the Foundry platform context. A nonempty platform
user ID, call ID and session ID are required in a Foundry-hosted environment.
The runtime actor comes from that platform user context, **not** the card data
or the activity's claimed name. The signed channel activity additionally binds
the tenant, Teams AAD object ID and conversation ID.

`documentation-teams-approvals-v1` stores these bindings per pending ID with
SDK user isolation. Every card submission/reopen checks all of them before
reading or deciding the pending call. Neither record IDs nor argument hashes
are secrets or sufficient authorization. Existing Responses-only v8 proposals
have no Teams-card binding and cannot be silently adopted.

The application relies on Foundry's authenticated ingress for platform headers
and channel validation. Do not expose its container port publicly, forge
`FOUNDRY_HOSTING_ENVIRONMENT`, or put an unauthenticated proxy in front of it.
Local handler tests substitute platform context/storage; they do not prove
cloud channel authentication.

## Input and delivery

`help`, `start` or `hej` displays guidance. Existing structured `propose` and
`propose_result` messages are accepted; all other decisions come from card
buttons. `show <pending-id>` reopens a card created by this adapter in the same
user/session/conversation. Free text is not automatically treated as a write.
The upstream assessment/PR caller still needs to submit the selected proposal;
this is not a natural-language proposal-generation feature.

The card callback is:

```json
{
  "interface_version": "1.0.0",
  "action": "approve",
  "pending_id": "<UUID>",
  "args_hash": "<64-character SHA-256>"
}
```

Other action values are `reject`, `edit`, `modify`, and `inspect`. Only `modify`
accepts `content` and `feedback`, which are mandatory, nonblank and bounded by
the existing runtime's limits. Unknown fields, altered hashes and forged
tool/identity/target fields are rejected.

The full serialized card is capped at 26,000 UTF-8 bytes, below Teams' common
28 KB limit. Oversized proposals fail visibly instead of showing a truncated
proposal with a working Approve button. A pending record can already exist when
rendering/delivery fails; it is not approved. Delivery failures after a decision
never cause the runtime to undo or replay the external action. Reopen status
and reconcile the target after an uncertain execution.

## Enable only in a reviewed new version

Install `.[agent,dev]` for development. The existing agent extra now includes
the Activity SDK, but its host remains disabled unless all settings are supplied:

```text
DOCUMENTATION_MODE=approval
DOCUMENTATION_ENABLE_APPROVAL=true
DOCUMENTATION_APPROVAL_POLICY=/app/approval/sandbox-policy.json
DOCUMENTATION_ENABLE_TEAMS=true
DOCUMENTATION_TEAMS_TENANT_ID=<approved-demo-tenant-UUID>
```

`main.create_server()` composes `/activity/messages` and the unchanged
`/responses` routes on one port. Non-approval modes reject the Teams enable flag.
The host builds its outbound Bot Connector authentication from the existing
Foundry identity using the official SDK. No secrets or operator CLI credential
are added.

Deployment must explicitly declare native **activity** plus **responses**
container protocols (2.0.0), preserve the existing identity/approved tenant
channel authorization, and verify the existing Bot Service uses that agent
instance identity. Merely adding `activity` to the stable endpoint, as portal
publishing does for Responses bridging, is not enough to select native Activity
handling in the new container.

Do not change the served version while another session is testing. Retain v8
and its image for rollback. New native-Activity tests need fresh sessions and
fresh proposals; old pending records/session mappings are not migrated.

## Verification and remaining acceptance

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\agents\test_teams_approval.py tests\agents\test_tool_approval.py `
  tests\agents\test_approval_spike.py -q
```

Local coverage exercises card generation, callbacks through the real Activity
and Responses hosts, unchanged native Responses approvals, exact-call dispatch,
Reject/Modify, stale and competing decisions, restart/reopen, tampered fields,
tenant/user/conversation/session isolation, expiry and uncertain outcomes.
Tool calls and channel delivery are test doubles; no real wiki writes occur.

### Live Teams evidence (2026-10-20)

The user verified in a fresh personal Teams conversation on the served v13:

| Path | Observed result |
|---|---|
| `help` and proposal | Native cards render with the sandbox target, exact content, evidence and all three decision buttons |
| Reject | Result card reports `Proposal rejected`; repeating Reject on the old card is refused as no longer pending |
| Modify | Form produces a new pending ID and the exact revised text; the old proposal is invalidated; replacement Reject succeeds |
| Approve | Result card reports `Tool reported success`; independent ADO GET confirms the exact approved full page |

Approve run `9768b3ac-4f94-465f-873a-66cc528c9456`, pending
`68f85c83-f089-44d9-9a5f-fadfbc8dd6ab`, decision timestamp
`2026-10-20T11:02:52.095624Z`. Arguments SHA-256:
`095823818c14f5e6105a44371d3685337ad9ab6e7bc808a0186ae538a5600e16`.
The page retained the earlier sandbox paragraph and added only the run's unique
Teams test marker. The operator performed read-only checks before and after;
the user initiated the write through Approve, not an operator REST write.

Reject/Modify are user-observed UI evidence, not independent gateway call-count
audits. Approve includes independent target readback but does not prove an
exactly-once external transaction. That sandbox test did not supply an ETag; the user
confirmed no concurrent editing of the sandbox during the test.
Evidence is recorded on [#16](https://github.com/wdhm/foundry-agentic-pattern/issues/16#issuecomment-6289412106)
and [#1](https://github.com/wdhm/foundry-agentic-pattern/issues/1#issuecomment-6289412441).

Remaining acceptance documentation includes real-client screenshots/mobile
verification and reconciliation of the tickets' audit requirements.
This feature does not implement Cosmos audit, whole-page composition,
automatic PR-to-Teams posting or a broader write allowlist.
