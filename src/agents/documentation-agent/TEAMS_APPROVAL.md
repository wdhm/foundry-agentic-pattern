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

### Review-experience update (not yet deployed)

The new cards pair a status icon with readable state text and Teams semantic
colors: Accent for review/processing, Good for published, Warning for expired,
Attention for unknown outcomes and neutral for rejected/replaced. Color is never
the only status cue. The original heading format, layout, Draft/Changes/PR links,
decision buttons, technical IDs and expiry fields are retained. Only the heading
icon/color and state-appropriate feedback are enhanced, rather than a card redesign.
Terminal cards do not tell the reviewer to approve again. Outgoing cards have no separate
text body, avoiding duplicate-looking Teams messages.

**Compact Modify form:** only the page target (when available), one explanation,
the complete editable draft, the required reason, **New proposal** and **Cancel
edit** are shown. Tool arguments, evidence excerpts, hashes, run IDs and expiry
details remain on the full review screen, not repeated inside the editing form.
The complete content value and validation limits are unchanged. Opening or
cancelling the form does not change the proposal; submitting still invalidates
the original and requires a separate approval. Expired/terminal proposals never
render editable controls.

New wiki drafts use this hierarchy:

```text
/Drafts/Order Sync/PR-<number>/
  Review-<event UUID>/
    Draft
    Changes
    Revisions/
      Revision-<revision UUID>/
        Draft
        Changes
```

The parent pages are application-managed navigation containers, not integration
documentation. The publisher creates them only within its generated path grammar.
Each PR event is claimed before publication as before. Revisions retain the
original review and create new leaf pages; the old approval is invalidated.
Approval checks bind **Draft** to its sibling **Changes**. Legacy flat paths
remain readable for existing approval validation but are no longer generated.
Do not author manual content in generated parent pages. No cleanup happens
automatically in the runtime.

On 2026-10-29 the user explicitly authorized removal of the old demo pages.
Twelve inventoried PR 1-6 draft/review leaf pages were backed up locally, deleted
individually with their current ETags, and confirmed absent. The root/Order Sync
parent pages and published wiki content/ETag were preserved. Old card links to
those demo pages no longer work; old write approvals cannot pass draft readback.
New approvals require a fresh event, not a retry of those removed drafts.

**Durable decision acknowledgement is separately opt-in:**
`DOCUMENTATION_ENABLE_DURABLE_DECISIONS=true`, with the existing hosted channel,
push-flow and bot identity configuration. The default synchronous behavior is
unchanged when the flag is off.

The core/Responses/Invocations/Activity hosting SDKs are explicitly pinned in
`pyproject.toml` to the tested composition. A clean candidate build on 2026-10-29
otherwise resolved newer core/Responses prereleases and logged `TaskManager NOT
initialized` despite declared tasks and the opt-in flag. That candidate was not
promoted. SDK upgrades must pass the composed-host task lifecycle test and show
`TaskManager initialized with startup recovery` in hosted startup logs; a successful
Responses greeting alone does not validate the queued Teams path.

For channel Approve/Reject/New proposal submissions, the handler validates the
signed actor, scope and saved proposal, persists one decision job per pending ID,
and starts a registered Foundry SDK resilient task. It then returns **Decision
received - processing**, not a publication success. The worker rechecks the
current member, event, draft and wiki version through the existing approval path,
and sends the final result to the saved channel root. Task input is only the job
ID; actor/action/activity data comes from the server-created durable record, not
caller-supplied task input. Platform user context is never forged on recovery.

**Initial Review now uses the same opt-in queue:** the `review_push` card action
validates the signed channel binding and current event/policy, stores one
`review-<event-id>` job, and returns **Opening review** after task submission.
The worker rechecks current channel membership and event/thread eligibility before
creating or reopening the shared pending proposal and posting its review card.
It never submits an approval or writes wiki content. Repeated clicks share one
job and preserve its original requester. Completed duplicate clicks direct users
to the existing card; a failed/claimed job is not automatically replayed. A
processing failure posts **Review needs attention** when delivery is possible.
Source and membership failures are not converted into apparent success.

Jobs use the separate `documentation-channel-decision-jobs-v1` shared store.
An execution claim is persisted before processing, task failure retries are
disabled, and a recovered already-claimed job **does not replay the decision**.
A crash between job claim and final delivery requires operator reconciliation;
the pending approval state is the publication authority, not task completion.
Failed processing sends an attention card when delivery is available. Failed
result delivery never retries the wiki write. Refresh status hides decision
controls while a pending proposal has an outstanding job.

The local SDK task lifecycle and slow-write/review-preparation tests demonstrate
that enqueue does not wait for the external operation. **This is not yet live proof of a Teams timeout
fix.** Hosted resilient-task availability, survival after HTTP completion,
membership checks and final-card delivery must be validated on an isolated
candidate before enabling the flag for the shared deployment. Incoming identity,
team metadata and durable submission still take time; no absolute latency bound
is promised. Status reads, opening the Modify editor, text `review <event-id>`,
registration and personal-chat actions remain synchronous; their latency may
still produce a Teams banner. No generic early success or
untracked `asyncio.create_task` write is used.

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

By default, only personal Teams chats in `DOCUMENTATION_TEAMS_TENANT_ID` are
accepted. The optional channel mode below permits one explicitly configured
team/channel; arbitrary group chats and other channels remain rejected.
Organization-wide catalog visibility does not grant approval authority.

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

## Shared channel reviews

Enable `DOCUMENTATION_ENABLE_CHANNEL_REVIEWS=true` only alongside Teams, approval
and the merged-PR **wiki draft** flow. Set `DOCUMENTATION_TEAMS_CHANNEL_POLICY` to
an operator-reviewed JSON file:

```json
{
  "tenant_id": "<tenant UUID>",
  "team_id": "<Teams team ID from a verified channel activity>",
  "channel_id": "<Teams channel ID>",
  "channel_type": "standard",
  "reviewer_mode": "channel_members",
  "reviewer_aad_ids": []
}
```

These are placeholders, not a deployable policy or a grant to any named person.
`tenant_id` must match `DOCUMENTATION_TEAMS_TENANT_ID`. The user-selected
`channel_members` mode permits every current member of the configured standard
channel, including guests who are members, and must not also specify an allowlist.
An optional `allowlist` mode instead requires a nonempty, unique list of reviewer
Entra object UUIDs. A Teams team ID is an opaque channel-context identifier;
do not substitute an Entra group UUID without verifying the Teams activity.
Alternatively set `team_aad_group_id` to the group UUID from the selected channel
link and omit `team_id`. Missing `aadGroupId` in an incoming activity is resolved
through the authenticated bot's team-details API, requiring both the internal
team ID and returned group UUID to match. Conflicting values are never overwritten.
The policy is loaded at startup. In allowlist mode, deploy an updated policy to
revoke/add reviewers. In membership mode, the adapter uses the authenticated
turn's Bot Connector to fetch the current sender's conversation-member record;
the returned channel-user ID and Entra object ID must match the acting user.
The lookup is bounded to 20 seconds, not cached, and repeated immediately before
the approved-write state claim after tool/wiki checks. A missing member, identity
mismatch, missing connector, denied roster read or timeout prevents the decision.
It uses the existing Bot identity/SDK, not a new Graph permission grant. This
must be verified live for the selected standard channel before activation.
The legacy `PushPolicy.reviewer_aad_id` remains required for
backward-compatible personal mode but does not authorize channel decisions.

Before activation, verify the published Teams app manifest permits the **team**
bot scope and install the app in the selected team using the tenant's approved
app-management process. Existing personal-scope publication alone is not proof of
channel availability. Standard channels in the configured tenant/public cloud are
the initial deployment target; private/shared channels and guest/cross-tenant
scenarios have not been validated. Do not change app scopes, install an app, or
grant wiki access implicitly. All channel members can see the posted draft links
and bot replies; ensure those sources are appropriate for that audience. Each user
still needs independent Azure DevOps access to open the wiki links.

A current channel member (or allowlisted reviewer in that mode) @mentions the agent with `help` and selects **Enable
channel notifications**, or sends `@agent enable notifications`. This registers
the notification destination, not a repository credential. It survives ordinary
session/version changes while SDK state is retained; enabling it also requires
the live membership check in membership mode. The existing personal
subscription is stored separately and is not overwritten. With channel mode
enabled, new pipeline events go only to the configured channel subscription;
personal subscriptions/approvals are not silently migrated or broadcast.

For each merged PR, the existing pipeline assesses the exact snapshot and writes
restricted wiki draft/review pages. The bot makes one SDK create-conversation call
to start a **new channel thread** containing the links and Review button. The
returned conversation/root IDs are persisted before the event becomes `notified`.
An uncertain notification or missing thread identity is not automatically retried.
The SDK outbound middleware keeps subsequent cards and answers addressed to that
root; it does not post them as new channel roots.

Anyone in the configured channel can open the review and ask questions. Opening
creates **one shared pending proposal**, not one per reviewer. In membership mode,
every current member can Approve, Reject or Modify after the roster check. In
allowlist mode, a viewer's rendered card omits decision controls, but server-side
authorization still rejects clicks on controls visible in cards posted for another
reviewer. Every callback binds the tenant, team,
channel, conversation and root thread from the authenticated Activity, not card
values. The two authenticated identity values are retained: the platform actor
and the clicking user's Entra object ID.

`documentation-channel-approvals-v1` is a separate SDK store with
`user_isolation=false`, accessed only through the scoped channel adapter.
Records use runtime `0.7.0`, retain their original creator/session for attribution,
and add `shared_scope`, `decided_by_aad_id` and (when applicable) `membership_checked_at`.
Personal records continue using
their user-isolated store and owner/session checks. Shared approval IDs cannot be
used through the Responses approval endpoint. The underlying exact-call runtime
still performs schema/hash/expiry/draft/notes/base-ETag checks, a conditional claim,
one external dispatch attempt and exact destination readback.

The first successful state claim wins, including Approve-versus-Reject races.
Later clicks show the persisted winning state and decision-maker, never dispatch
again. Modify claims/voids the old proposal **before** publishing a draft revision,
so it cannot race an approval of the old content after that claim. The revision
gets a fresh pending ID; any currently authorized reviewer/member may decide it. Revision
failure leaves the old proposal void and may leave an orphan draft; do not retry
uncertain side effects. A timeout after dispatch remains `outcome_unknown` for all
reviewers, not a retry button. Newer accepted PR events still supersede older
pending reviews. This is not a distributed transaction or a Cosmos audit log.

Read-only questions stay in the review thread. The stored thread/event binding
adds only that event's verified draft/notes pages and exact source commit to the
conversational read scope. The model gets no decision capability. Chat history
remains per user/session/thread; private personal-chat history and another
participant's history are never injected into replies visible to the channel.
There is no ingestion of the entire Teams thread; users should @mention the bot
with the relevant question. Updated draft revisions get a new source-policy hash.

Local SDK integration tests exercise registration, new-thread creation, mention
stripping, root-thread reply routing, two distinct reviewers, viewer refusal,
cross-thread/tenant rejection, decision races, revision invalidation, source
changes and uncertainty. Live proactive delivery and multi-person approval still
require channel acceptance; the rollout below records only confirmed milestones.
See [Teams proactive messaging](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/send-proactive-messages)
for installation and conversation prerequisites.

### Channel rollout evidence (2026-10-23)

The user selected **Peab Wiki Updates** and authorized every current channel
member to decide. Hosted v29 is selected at 100%, retaining the existing identity,
Bot and approved publication, with v26 available for rollback. It uses runtime
snapshot manifest `e7b0d5512ca12d6c1f6925696d046c5dcddf76f1763c931e640c29e2d9190b22`
and image
`sha256:6edbd1158ef19111e085893d1934b6da978b3e0c0a402494f8f14bcd70be3f1a`.
Source is the uncommitted `feat/teams-channel-reviews` snapshot based on
`c2cf4fefb17f83c678e1e18f6a747c964c707a69`, not a merged release.

The user confirmed **Repository notifications connected** in the channel. This
response follows successful bot-side team resolution, standard-channel and
sender-membership verification and persisted registration. A direct session GET
confirmed v29 for that actual Teams session. No WorkIQ account switch or new
permission grant was required. Full channel draft delivery and approval/readback
are not yet proven by this registration.
Pipeline 1 was then pinned from v26 to v29 without changing its reviewed caller
source or trigger filters. Identity-only preflight build 7 succeeded and returned
`caller_verified`, `assessment_run: false`; it created no documentation draft and
authorized no publication.

**First proactive channel test failed (2026-10-23):** comment-only Azure Repos
PR 3 merged as `7c754b99f9e5960742a0e3f6d645f9684c532827`, triggering build 8
against v29. Assessment and both wiki draft pages completed for event
`d4237373-9d32-53fb-b347-cd9be264f618`. The Bot Connector returned HTTP 400
from `POST v3/conversations` while creating the new channel post. Runtime
telemetry recorded `notification_unknown`; no automatic notification retry was
performed. The SDK raised `ClientResponseError` without retaining the response
body, so the specific payload rejection is not yet established. Independent
wiki reads confirmed unchanged published content and ETag. This is not a
successful end-to-end channel test; channel registration alone does not prove
proactive thread creation. Evidence is under `.azure/channel-demo-20261023/`.

**Single-card delivery confirmed (2026-10-23):** the one explicitly requested
PR 3 notification retry on v31 captured Teams' diagnostic:
`HTTP 400: BadSyntax Activity resulted into multiple skype activities`.
This is Teams' internal service terminology, not a Skype destination.
The root-post payload included both text and an Adaptive Card; v32 sends only
the card. The SDK still establishes the authenticated connector; a bounded
one-shot request retains redacted error details and uses SDK-managed cleanup.
No automatic transport or application notification retry is added.

The guarded `retry notification <event-id>` channel command consumes at most one
explicit retry after current-member authorization, matching destination/current
event/policy and unchanged draft/notes/target checks. It never regenerates the
draft, re-runs assessment, authorizes publication or resets an uncertain attempt.
PR 3's retry was consumed and was not reopened for the next test.

User-authorized v32 rollout preserved the collaborator's v30 read-Toolbox-v4
configuration and all current identity/publication settings (v31 rollback).
Image `sha256:6a1d2bee6c701a176a387d17e82ddc6e053a3bd1ff3d941ce7f8cfa58d7e705b`,
source manifest `c9ddbd3c16be0306684065576b84fefde7b457118c914389c1f68bfd7f4c83d6`.
Pipeline 1 is pinned v32; build 9 verified the workload without assessment.
Fresh comment-only PR 4 merged as `f86e851de0379124d8de0a2b75d1026f5d129504`;
automatic build 10 succeeded with `notified`, `duplicate: false` for event
`0b31ac88-54e7-530c-a119-40f5a7d2face`. That acknowledgement follows successful
channel-post creation and persisted root-thread binding. Both draft and review
notes were independently readable; the published wiki content and ETag matched
the pre-test baseline. Evidence: `.azure/channel-deployment-v5/` and
`.azure/channel-demo-single-card/`. The channel source is still unmerged.

**Human channel approval verified:** the user reported that the PR 4 card appeared
and they approved it, providing a screenshot of the `succeeded` result card for
pending `300c7d3a-5e85-4afa-8a76-88e466e0aa61` with their Entra approver identity.
Independent ADO reads at `2026-10-23T11:48:41Z` confirmed `/Order Sync/Overview`
exactly matched the saved PR 4 draft; the draft was unchanged. Published ETag
changed from `bad767986ce7bc8ee63da0b1408bedaf7e533aca` to
`0b32ae7da6667c40710889e17326441f487e7427`, also matching the draft's blob ETag.
This confirms merged PR -> channel review -> human-approved wiki publication for
one reviewer. A second distinct human approver is not yet live-tested.

**Remaining UX defect:** Teams displayed "Something went wrong. Please try again."
above the old actionable card even though the success card arrived. Correlated
operation `071b7068c484e0e489ad78fe79b4f0a7` reported successful agent execution
in 14.54 seconds and HTTP 202 from `/activity/messages` after 16.22 seconds, with
no correlated server error in the inspected telemetry. A Teams action
acknowledgement timeout is consistent with this evidence, but client-side timeout
telemetry was not captured. Do not retry the approved write. A future UX fix must
acknowledge promptly while preserving durable claims, actual final-result delivery,
runtime lifetime and no blind retry; detached in-memory write tasks are not safe.

v27 exposed a card/root-thread mismatch: card callbacks can address a bot reply
while the conversation's `;messageid=` suffix identifies the root. v28 fixed that
without removing cross-thread binding; v29 resolves a missing Entra group ID
through the bot connector. Existing Teams sessions stayed pinned to older versions
even after new posts, while request telemetry displayed the newer serving version.
Two exact failed test sessions were reset only after user approval; the first
reset targeted an earlier session, so the latest click's session was subsequently
identified through telemetry and reset separately. Always confirm the actual
session version by GET rather than relying on endpoint/outer telemetry labels.
Evidence is retained locally under ignored `.azure/channel-deployment-v3/`.

## Input and delivery

`help`, `start` or `hej` displays guidance. Existing structured `propose` and
`propose_result` messages are accepted; all other decisions come from card
buttons. `show <pending-id>` reopens a card created by this adapter in the same
user/session/conversation. Free text is not automatically treated as a write.
The upstream assessment/PR caller still needs to submit the selected proposal;
this is not a natural-language proposal-generation feature.

With the separately enabled [conversational path](README.md#optional-conversational-toolbox-path),
ordinary text receives a read-only model/Toolbox answer as a normal Teams message.
The existing personal-chat/tenant/platform-user checks run before chat too.
Questions and follow-ups do not require JSON. JSON-shaped commands still fail
closed if malformed, card actions never fall back to the model, and conversational
agreement never becomes an approval. Chat is disabled by default in code. After
isolated Responses acceptance, v26 was explicitly selected for Teams on 2026-10-22.
The user confirmed fresh notification registration and merged-PR build 6 reported
delivery; final wiki approval/readback is pending. The approval flow does not require chat.

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
