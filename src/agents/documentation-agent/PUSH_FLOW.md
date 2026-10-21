# Azure Repos main push -> assessment -> personal Teams review

**Integration increment; not yet live-enabled.** This goes beyond the manual
workflow MVP in ADR 0022. It reuses the Azure Repos reader merged in #93, the
normal assessment runtime and the native Teams approval handler from #94.
The initial scope is one repository, `refs/heads/main`, one registered reviewer
and `/Workshop/Approval-Sandbox`. It is not a PR-comment implementation of #30.

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

The proposed content is a complete, deterministic **sandbox review report**:
assessment status, findings, proposed sections and supplied evidence. It replaces
only `/Workshop/Approval-Sandbox`, not `/Order Sync/Overview`. This avoids
pretending section fragments can safely replace the actual integration wiki.
The card presents the full sandbox content and target before approval.

There is no automatic merge into existing wiki sections and no ETag protection
in the existing P2 write tool. A demo Approve still needs an exclusive sandbox
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
the two source files, uses `batch: true`, and has no PR execution. All main
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

### Prepared cloud foundation (2026-10-21)

With explicit user approval, a dedicated `id-ado-push-teams` managed identity,
`fap-push-teams` Azure DevOps service connection and exact returned Entra
federated credential were created. Only project-scoped Foundry Agent Consumer
was assigned. The connection reports ready; this is not proof of a successful
federated pipeline run. No pipeline trigger or new serving version was enabled
by this preparation.

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

## Acceptance still required

Local tests use the real triple-protocol SDK host with model/tool/delivery
doubles. Live acceptance requires a federated pipeline run, an authenticated
`connect repo`, a real main push, observed assessment output, proactive card,
and reviewer decisions against the sandbox. Do not claim this works merely
because identity resources or the YAML exist.

This increment cannot alone close PR-specific #30: PR triggers/comments and
timing evidence remain. Full audit/commit attribution and real documentation
composition also remain outside this sandbox flow.
