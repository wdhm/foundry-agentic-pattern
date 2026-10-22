# Azure Repos main push -> assessment -> personal Teams review

**Live main-push increment, verified 2026-10-21.** This goes beyond the manual
workflow MVP in ADR 0022. It reuses the Azure Repos reader merged in #93, the
normal assessment runtime and the native Teams approval handler from #94.
The initial scope is one repository, `refs/heads/main`, one registered reviewer
and `/Workshop/Approval-Sandbox`. It is not a PR-comment implementation of #30.

## Merged-PR draft review (new code; not live-enabled)

Package 0.8.0 adds this mode and conditional-page approval engine 0.6.0;
assessment provenance is unchanged. Set `merged_pr_drafts: true` in a reviewed push policy and use the updated pipeline
template to opt into the post-merge flow. The previously deployed main-push flow
remains unchanged until that coordinated rollout.

1. A main CI run queries completed Azure Repos PRs using the scoped pipeline job
   token. It requires exactly one PR whose successful `lastMergeCommit` matches
   the triggering commit, whose target is `refs/heads/main`, and whose repository
   is the configured repository GUID. It reads that PR back before proceeding.
   Direct pushes, open PRs and abandoned PRs do not produce assessments/cards.
   No heuristic based on a commit message or merge-parent count is used; squash
   and other supported strategies are identified through Azure DevOps metadata.
2. The authenticated pipeline passes the verified PR ID to the existing endpoint.
   The runtime validates the workload/policy, attaches the source PR to the
   assessment and saves the exact proposed content. It returns `draft_ready`
   without sending a notification or authorizing a wiki write.
3. The pipeline creates `refs/heads/documentation-drafts/<event-id>`, based on the
   exact merged commit, with `/documentation-drafts/<event-id>.md`.
   Real-page mode also includes `<event-id>-review.md` for the diff/evidence.
   It never commits that file to main, opens a code PR, edits a wiki page or
   force-pushes. A retry may reuse an already-created exact draft; edited content
   or a changed parent causes an explicit failure instead of overwriting it.
4. The pipeline submits only the returned immutable draft commit ID. The runtime
   reads the exact file through the existing read Toolbox, verifies repository,
   commit, path and content bytes, then sends a short Teams notification.
5. **View draft** opens the Azure Repos Markdown file at that exact commit
   (`version=GC<sha>`), using existing Azure DevOps sign-in and repository
   permissions. **Merged PR** opens the source PR. **Review decision** creates
   the reviewer-owned pending call and displays a compact card with these links
   and Approve/Modify/Reject. The saved pending content equals the verified draft.

By default the file remains the **complete sandbox review report**. The new
`compose_wiki_page: true` option instead prepares the **actual final wiki page**
as described below. Both modes show the explicit target in the card, and neither
publishes to the wiki without a separate human approval.

### Actual integration-page updates (local implementation; rollout pending)

The user selected `/Order Sync/Overview` as the real documentation target.
Enable **both** `merged_pr_drafts` and `compose_wiki_page` in the push policy,
retain `wiki_page: "/Order Sync/Overview"`, and explicitly select
`approval/order-sync-policy.json` as `DOCUMENTATION_APPROVAL_POLICY`.
That policy is restricted to this page and requires a dynamic `etag` argument.
The existing sandbox policy is unchanged and does not acquire this permission.

The workflow:

1. Read the current page **and its ETag** through the read Toolbox. Validate
   the returned page path and that its UTF-8 content hashes to the wiki Git-blob
   ETag. A missing page/version is an error, not an empty-page fallback.
2. Run normal evidence-checked assessment of the merged source commit. Read the
   page again and require the same snapshot, with assessment wiki evidence at
   that version. A concurrent edit during assessment stops draft generation.
3. Compose the complete document deterministically from the existing page and
   the proposed sections. Preserve the title, introduction and every unrelated
   section byte-for-byte; replace only explicitly targeted H2 section bodies,
   or append missing H2 sections. H3+ subsections belong to their enclosing H2.
   Existing source links and manual content outside changed sections remain.
4. Publish **two** separate, commit-pinned Markdown files on the draft branch:
   the final page content, and review notes containing the before/after diff,
   base ETag, findings, unresolved information and evidence. Review notes are
   never inserted into the wiki. The runtime reads both files back and checks
   their exact bytes before sending the notification.
5. The Teams card links **View draft**, **Changes** and **Merged PR**. Opening
   the decision binds the complete page content and its base ETag into the
   pending call's argument hash. Modify retains that base version; it does not
   silently rebase an approval onto newer wiki content.
6. On Approve, read the page and reject a changed ETag before dispatch. Send
   the approved `etag` explicitly to `ado___wiki_upsert_page`; never omit it
   or substitute the current version. The recorded live tool schema includes
   this parameter. After the tool reports success, independently read back the
   page and require exactly the approved content before reporting success.

The composer is intentionally bounded, not a general-purpose Markdown editor.
It supports ATX headings and fenced code blocks, including explicitly grouped
H2 proposals. It rejects ambiguous duplicate section names, conflicting
proposals, page-title replacement, raw HTML blocks, Setext headings, unclosed
code fences and oversized results rather than guessing or truncating.
An unrelated title/section is never silently deleted. This verifies composition,
not the truth of model-authored text: the reviewer must still check the diff,
uncertainties and evidence before publication.

**Live proof still required:** a remote stale-ETag request must demonstrably fail
without overwriting the newer page, and a matching-version approved update must
pass exact-content readback. Schema support and local tests alone do not establish
the remote service's conditional-write semantics. Some wiki upsert implementations
try creation first; deletion/recreation races therefore also need verification
before claiming full optimistic-concurrency protection. If the service does not
honor the expected version, use a verified conditional-update tool; do not disable
this check or fall back to a last-writer-wins update. For the workshop, coordinate
exclusive editing until those live checks are established.

Readback failure after dispatch remains `outcome_unknown` and non-retryable.
The pending record retains the approved ETag and arguments; successful conditional
writes add the verified page path/URI/new ETag to their receipt. The draft branch
and its pinned commit stay available after Approve or Reject as review history;
no automatic deletion, source-branch merge or retention job is introduced.
New runtime policy fields may invalidate old policy-hashed pending approvals;
create fresh drafts, never migrate or alter an approval behind the user.

### Modified drafts and link integrity

The link is never switched to a mutable branch head or to an edited file.
Editing the branch externally does not change the commit-pinned review link or
the saved approval arguments. External edits are not automatically imported.

**Modify** retains the existing explicit content/feedback editor. If the revised
content differs from the linked draft, its new summary card removes **View draft**
and offers **Review revision** instead of Approve. That explicit action shows
the full revised content and fresh decision buttons. This deliberately preserves
safe review rather than pretending an old link represents a new proposal.
Automatic publication of revisions from Teams is not implemented; it would need
its own publisher handoff. The unmodified, common path stays compact.

### Rollout and access prerequisites

- Keep the feature off until the updated runtime and caller are deployed/pinned
  together. The old deployed caller does not publish drafts.
- Map `SYSTEM_ACCESSTOKEN: $(System.AccessToken)` only into the publisher task.
  This is a distinct Azure DevOps job identity, not the federated Foundry caller.
  It needs repository/PR read, creation of the dedicated draft branches and
  contribution there. Verify branch-scoped permissions and protect main; do not
  grant force-push, policy bypass or wiki-write permissions for draft publication.
  Draft content is visible to users with read access to that repo; confirm that
  this audience is appropriate for the assessment's source material.
- The hosted agent needs only its existing `repo_file` read capability to verify
  the draft. The job token is never sent to Foundry, logged or stored in state.
- Disable CI batching in both YAML and the registered pipeline definition:
  batching can coalesce distinct merges and lose an intermediate PR review.
  Preserve the existing source-file filters and pipeline-specific federation
  permission. Source-repo draft-branch pushes do not match the main filter.
- Keep the prior serving version until a completed-PR test confirms the job-token
  permission, draft creation, exact-content readback, authenticated link access
  and compact Teams delivery. Start with Reject, not a real documentation update.

This is a post-merge review: it cannot block or approve the original code PR.
The runtime trusts the policy-allowed pipeline to attest the ADO merge lookup;
it does not treat arbitrary public webhook bodies as verified merge events.
It still reviews the configured source snapshot, not only the changed PR lines.
Existing supersession/retention limits below apply. If automation configuration
changes, older policy-bound reviews are rejected rather than silently migrated.

## Flow

1. An Azure Pipeline starts after relevant files change on main. It executes
   only the caller from a reviewed immutable commit of this application repo,
   not scripts from the changing integration repo. PR triggers are disabled.
2. AzureCLI@2 obtains a workload-federated token. The caller creates/GET-verifies
   a concrete-version session and invokes the **Invocations** route. It sends
   pipeline/build IDs, the configured repository and exact commit, never a
   reviewer identity, tool arguments, expected answer or approval.
3. The runtime requires an exact configured platform caller identity and
   repository/branch/pipeline match. It claims a deterministic repository+commit
   event in a shared SDK store, rejecting duplicate/incomplete/stale events.
4. The existing `AssessmentAgent` reads the configured source files at that
   commit through the versioned read Toolbox and validates evidence. This is
   an **implementation snapshot review**, not a complete multi-commit push diff.
   Listed source paths are the operator's review scope, not a fabricated list
   of changed files.
5. The bot proactively sends a **Documentation review ready** card to the
   registered personal chat. Delivery uses the official M365 adapter and
   existing bot/agent identity. No write or pending approval is created by the
   pipeline.
6. **Open review** runs in the reviewer's authenticated Teams turn. The server
   checks tenant, AAD user, platform owner and conversation, then creates a fresh
   pending call in the current Teams session. Approve/Modify/Reject reuse #15.
   The pipeline never impersonates the reviewer or supplies their user header.

## What approval writes

In the deployed/default mode, the proposed content is a complete **sandbox review report**:
assessment status, findings, proposed sections and supplied evidence. It replaces
only `/Workshop/Approval-Sandbox`, not `/Order Sync/Overview`. This avoids
pretending section fragments can safely replace the actual integration wiki.
The card presents the full sandbox content and target before approval.

That mode does not compose existing wiki sections or supply an ETag. The tool
schema does support an explicit ETag; the new real-page mode above uses it.
A default sandbox demo Approve still needs an exclusive sandbox
editing window. Reports exceeding existing content/evidence/card limits fail
visibly; the runtime never silently drops evidence or truncates approved text.
No proposed changes means an informational review with no write buttons.

## Registration and authorization

The configured reviewer sends **`connect repo`** in a personal Teams chat on
the new version. The channel handler validates the signed-platform context,
configured tenant/AAD reviewer and Bot Connector service URL. It stores the
conversation reference in `documentation-push-flow-v1`. Only
`https://smba.trafficmanager.net` is supported by this public-cloud first version.
Different cloud/service URLs fail closed pending explicit support.

The pipeline inbox uses SDK `user_isolation=false` because pipeline and reviewer
are deliberately different identities. All access is mediated by strict
runtime caller/reviewer checks; raw store keys/recipient references are never
accepted from trigger payloads. Pending approvals remain user-isolated in the
existing approval store. Do not expose container ports outside authenticated
Foundry ingress or spoof platform identity headers.

`DOCUMENTATION_PUSH_POLICY` points to operator-reviewed JSON:

```json
{
  "repository_url": "https://dev.azure.com/foundry-agentic/integration-team/_git/8321c788-67e4-473c-9ad0-9f8847d077e1",
  "branch": "refs/heads/main",
  "pipeline_id": 123,
  "caller_id": "<verified workload platform identity UUID>",
  "reviewer_aad_id": "<designated reviewer AAD object UUID>",
  "source_paths": ["src/order_sync.py", "config/settings.json"],
  "wiki_page": "/Order Sync/Overview",
  "work_item_ids": [1],
  "documentation_standard_ref": "<reviewed documentation-standard reference>",
  "sandbox_page": "/Workshop/Approval-Sandbox"
}
```

The example pipeline ID and placeholders are **not deployment configuration**.
Confirm that the platform user ID delivered for the federated workload is the
configured principal; do not weaken the check or send a reviewer header if it
differs/is absent. Runtime identity propagation must be proven in a live probe.

Additional startup settings:

```text
DOCUMENTATION_MODE=approval
DOCUMENTATION_ENABLE_APPROVAL=true
DOCUMENTATION_ENABLE_TEAMS=true
DOCUMENTATION_TEAMS_TENANT_ID=<demo tenant UUID>
DOCUMENTATION_ENABLE_PUSH_FLOW=true
DOCUMENTATION_PUSH_POLICY=<mounted policy JSON>
DOCUMENTATION_PUSH_READ_TOOLBOX=<versioned read Toolbox with repo_file>
DOCUMENTATION_ADO_ORGANIZATION=foundry-agentic
```

Existing model/project/wiki settings remain required. Only the assessment
instance receives the read Toolbox override; the approval policy continues to
point to the write Toolbox. Declare native `invocations`, `activity` and
`responses` protocol 2.0.0 in a new reviewed version. Preserve Teams publication,
bot identity, auth schemes and the old serving version until explicitly promoted.

## Pipeline setup

Use [`infra/pipelines/azure-repos-teams.yml`](../../../infra/pipelines/azure-repos-teams.yml)
in the Azure Repos integration repository. Replace reviewed runtime commit,
deployment version and service connection placeholders. The pipeline filters
the two source files and has no pre-merge PR execution. The new draft template
uses `batch: false`; the older live push setup below still records its original
batching configuration until rollout. All main
writers must be trusted; restrict edits to the YAML and service connection.
Grant the connection to this pipeline only, never all pipelines.

The dedicated identity needs **Foundry Agent Consumer** at the existing project
scope, not Contributor or Foundry User. It receives no ADO source/write grants:
source access and wiki tools remain the hosted agent's responsibility. Verify
session creation, invocation and stopping with this role before rollout; do not
broaden it silently if a platform permission is missing.

Federation trusts only the issuer/subject returned by Azure DevOps. Do not
construct the legacy `vstoken` issuer/subject. No client secret or PAT is needed.
The caller prints only event/session identifiers, not source content or tokens,
and stops only the pipeline-owned session. A timeout is not retried blindly.

### Cloud foundation and live result (2026-10-21)

With explicit user approval, a dedicated `id-ado-push-teams` managed identity,
`fap-push-teams` Azure DevOps service connection and exact returned Entra
federated credential were created. Only project-scoped Foundry Agent Consumer
was assigned. The connection is authorized only for pipeline
**`documentation-main-to-teams` (ID 1)**. Manual run 1 proved federated invocation
and returned `caller_verified` with `assessment_run=false`.

Source commit `fd68158d8a621baad7abc408ddb44e6134b7f3a4` (PR #101) was built in
ACR run `dtg`, with an operator-reviewed deployment-only push policy. Image:
`sha256:4d63c5b980ff04c87be3e329f23cbf400d1d7c80a57c15eb7ebb9268e642f09d`.
Hosted **v21** is selected at 100%, with the existing Teams publication and bot
identity preserved; v13 is retained. No new wiki/source permission was granted.

The user registered their personal chat using `connect repo`. An initial YAML
enablement did not queue CI because the REST-created pipeline had no registered
trigger. Its definition was then given explicit CI filters matching the YAML
(main, `/src/order_sync.py`, `/config/settings.json`, batching enabled).
Keep both the registered filters and YAML aligned when maintaining the pipeline.

A comment-only source change automatically queued
[run 2](https://dev.azure.com/foundry-agentic/integration-team/_build/results?buildId=2)
with reason **`batchedCI`**, source commit
`571ad37536ca2302d98da073255c6ae4f4ef0961`. It succeeded:

| Evidence | Observed result |
|---|---|
| Pipeline | Queued 11:00:33Z; started 11:00:50Z; completed 11:02:56Z |
| Notification result | `notified`, `duplicate=false`, at 11:02:41Z |
| Event | `ec80b096-48f4-5ba9-8bc7-218c82f4570c` |
| Stored assessment | `insufficient_information`, 3 findings, 4 evidence entries; exact pushed commit retained |
| User-observed Teams UI | Notification arrived automatically; Open review displayed the assessment report and sandbox approval card; Reject returned Proposal rejected |
| Pending call | `cc2ba5e5-558e-4834-bbb5-c9e95b002a2f` |
| Pipeline session | `0abf7d81158a78d800mba8cDOryX6Z6ymjL4gXMgEF9M3uOS5j`, GET-confirmed version 21, idle after caller's stop |

The user did not paste proposal JSON, and no Approve was requested for this test.
Reject is user-observed UI evidence plus the existing runtime checks, not an
independent gateway call-count audit. The inbox readback independently confirmed
the event/result/pending linkage. This is delivery and integration proof, not a
full quality evaluation or approved production-documentation update.

## Deduplication, failures and freshness

One repository+commit has one durable event. Successful duplicate deliveries
return its existing status. Partial/failed assessments, uncertain notifications
and partially opened reviews return explicit failures rather than creating more
work. The event state is `assessing`, `assessment_failed`, `ready`, `notifying`,
`notification_unknown`, `notified`, `opening` or `opened`.

The last accepted build invalidates older **Teams** reviews; overlapping pointer
updates use ETags. Modified proposals inherit event lineage. Reject remains
available for superseded pending calls. A policy change also blocks old approvals.
This is not an atomic transaction with the source repo: a newer push can occur
before its pipeline delivery, or race an already-dispatched write. Main batching
and controlled demo editing are required; stronger source/wiki concurrency is
future work. Existing non-automation Responses approval semantics are unchanged.

If notification delivery times out, it might already have reached Teams.
Do not rerun it blindly; the intended reviewer may use **`review <event-id>`** in
the registered conversation. A successfully opened review is bound to its actual
Teams session and cannot move to another session without a new explicit workflow.
An `opening` record after a crash needs operator reconciliation, not automatic
creation of another approval. SDK default retention is finite (30 days); this
is neither indefinite deduplication nor a Cosmos audit implementation.

## Remaining acceptance boundaries

Local tests use the real triple-protocol SDK host with model/tool/delivery
doubles. The live run above additionally proves workload authentication,
registration, a real push-triggered assessment, proactive delivery and reviewer
Reject. Automatic failure recovery, source/wiki concurrency guarantees, group
chat delivery and a complete PR-triggered approval story are not established.

The deployed main-push increment cannot alone close PR-specific #30: its exact
PR acceptance and timing evidence remain. The new post-merge draft/page-composition
code above needs separate live rollout; it does not post results on the source PR.
Full audit/commit attribution remain outside this flow.
