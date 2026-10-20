# Azure DevOps sources and workflow

## Target user flow

A relevant Azure Repos code change or wiki edit triggers A10. It reads the
implementation at an exact commit, compares the requested wiki and requirements,
and proposes evidence-backed documentation changes. The integration team reviews
the exact proposal in Teams. Rejection makes no wiki edit; approval authorizes
only the reviewed target/content, subject to a current-target version check.

Automatic triggering and Teams delivery are separate integrations, not effects
of uploading sample code or adding a source read tool.

## Fictional baseline created on 2026-10-20

Repository: [integration-team](https://dev.azure.com/foundry-agentic/integration-team/_git/integration-team).
Its initial `main` commit is `8c9ad675df1b05ffa77babd1b0e0ba0647f7bcb2`:

- `src/order_sync.py` and `config/settings.json` reproduce the pinned GitHub
  baseline `8a9c9f2acff643ed15a41e6b43f2f8eb18502b4f`.
- `README.md` explains the fictional sample and links the existing wiki/work item.
- The baseline retries three times with fixed five-second delays; there is no
  Service Bus listener, explicit ERP timeout or real dead-letter transport.

The existing wiki `/Order Sync/Overview` and work item 1 were not changed.
Original GitHub evaluation fixtures and their expected answers remain unchanged.

## Read integration prepared in code

The normal v1 request accepts the Azure repository URL as `subject.repo`, with
the repository GUID in its final segment. The
[example request](../../src/agents/documentation-agent/examples/azure-repos-request.json)
pins the actual baseline and uses the existing wiki/work-item context.

The source path reuses the existing agent-user MCP gateway and Foundry toolbox.
`DOCUMENTATION_ADO_ORGANIZATION` explicitly opts the runtime into one additional
tool, `ado___repo_file`. Without it, existing GitHub/wiki/work-item behavior and
the four-tool allowlist are unchanged.

Read-only MCP discovery on 2026-10-20 verified `repo_file` with
`action=get_content`, `repositoryId`, `project`, `path`, `version` and
`versionType=Commit`. A call using the P3 project account returned the pinned
`/config/settings.json` as an embedded text resource. This verifies the tool
schema/output with that user account, **not agency-mode access**. The tool
description warns that file content may be unavailable in agency mode.

The guard rejects another organization, project, repository or commit; branch
reads, directory discovery, path traversal and write actions are not enabled.
Returned resource identity is verified before recording evidence. Git evidence
uses the returned Azure DevOps file URI and the full commit SHA, not a fabricated
GitHub link. Both assessment and observed-record evaluation use the same guard.

## Hosted rollout record (2026-10-20)

The user authorized the coordinated source rollout and exactly one read-only
assessment, preserving the serving approval endpoint and Teams publication.
After Rickard's reported admin update, Graph readback verified the existing
Principal-specific agent-user consent includes `repos.read` while retaining
`Ado.Mcp.Tools wit.read wiki.read wiki.write`, the same client and linked user.

| Surface | Verified result |
|---|---|
| Gateway | Revision `ca-doc-agent-mcp--0000007`, healthy; toolsets `wit,wiki,repos`; existing identity and `ADO_MCP_READONLY=false` preserved for approval consumers |
| Read toolbox | New immutable `documentation-agent-readonly:2` adds only `repo_file`; original version 1 and default version 1 unchanged |
| Assessment | Non-serving `documentation-agent:11`, active; managed identity, assessment-only mode, organization opt-in, pinned read toolbox 2; no approval/evaluation enable flags |
| Source/build | Commit `ad0339aae053a9a31eed00efe8f7be6c63e27fd0`; ACR quick build `dtb` |
| Image | `acrfoundryagenticr8n3ld.azurecr.io/documentation-agent@sha256:aaf2b91689635c37dc1824f70e1283594da0c0e50ee41e31da88e7380c43a21c` |
| Serving | Approval version 8 at 100%; Activity/Responses, authorization and publication configuration unchanged; retained evaluation version 10 not modified |

The single fresh-session assessment returned a schema-valid `gaps_found` draft
with the expected runtime provenance, commit-pinned Azure Repos evidence for
both source files, and the wiki ETag
`d897eaf7cd02c4da6bd70df5cae951ba6790df9f`. No operator token was substituted
for agent-user source access. This is diagnostic evidence, **not a passing
end-to-end acceptance result**: the GET-confirmed session binding was version
11, but the outer response identified version 8. The invocation guard rejected
that disagreement. No second assessment or serving/publishing change was made.
Test-session compute was stopped afterward; session metadata was retained for
the routing investigation.

Correlation for P2's routing investigation:

- Session: `033e860e9af9097000nkQp9sRykTYpqD8irejEnOl23kGWOg1T`.
- Response: `caresp_0fdabeea6d8ae11300V6C440co2CKg2F9Kid4oQkcDOj1OOlMZ`.
- Request: `644e656c-1d2c-4a23-b23d-b497d5c936d5`;
  correlation: `79435ea8-a744-4717-83a2-e4037aab4cd5`.

The unpublished draft proposes documenting mapping, configuration and retry
behavior. Its wording about queue-triggered handling still needs human review:
the sample declares a queue configuration but does not implement a Service Bus
listener. Do not treat the draft as proof of a running integration or publish
it unchanged. No wiki edit, Teams message or automatic event was sent.

P2 must resolve supported version-specific Responses routing before candidate
certification can proceed. Do not weaken the version guard or move serving v8
merely to obtain matching metadata; any additional model assessment needs fresh
authorization. No paid evaluation or generated evaluation suite was run.

## Rollout gates

Initial read-only live inventory during this change found the shared endpoint already
serving approval version 8 at 100%, with Activity/Responses protocols,
BotServiceTenant authorization and publication marked approved. This is ahead
of the dated main-branch v7 record, not proof of successful Teams delivery.
Gateway revision 6 then restricted upstream toolsets to `wit,wiki`. The
Microsoft Azure DevOps MCP resource declares the enabled delegated read scope
`repos.read`; `repos.write` and `repos.manage` are not needed for assessment.
No shared configuration was changed by that initial inventory; the separately
authorized rollout above records the subsequent changes.

1. Coordinate with P1/P2 before changing the shared gateway or serving agent.
   Inspect the current hosted identity, gateway toolsets and delegated consent.
   Add only the verified `repos.read` scope if absent, retaining current wiki
   approval permissions; never replace the grant with a guessed scope set.
2. Prove `repo_file get_content` works as the actual agent user, at the pinned
   commit. If agency mode rejects it, stop for a supported connector decision;
   do not substitute the operator's token or disable identity validation.
3. With explicit configuration approval, publish a new read toolbox using
   `setup-toolbox.ps1 -AzureRepos -NewVersion`. Preserve the separate write
   toolbox and existing versioned consumers. Add only the required gateway
   repository toolset; do not repoint identity or broaden assessment writes.
4. Review and deploy a new immutable assessment artifact with the organization
   setting and new version-pinned toolbox endpoint. Existing deployed versions
   do not acquire this support from a Git commit. Omit `PORT` from the Foundry
   environment variables: it is platform-reserved; the reviewed Dockerfile
   already supplies port 8088.
5. Authorize one read-only assessment with fresh request/correlation IDs. Verify
   session/outer version agreement, provenance, actual repository/wiki reads and
   result evidence before claiming hosted integration.

## Automatic events and Teams remain separate

No service hook, webhook receiver, pipeline, Teams notification or wiki write
was configured by this source-integration change. Before enabling automation,
agree the authenticated event receiver/hosting and target Teams team/channel.

The event adapter must validate its sender and configured repositories, resolve
actual changed paths and exact source commits, then build the same v1 request.
A wiki-triggered review must bind its wiki revision and a deliberate code
baseline; a code repository push is not a wiki edit event.

Deduplicate event IDs, suppress attributable agent-authored wiki updates, and
coalesce stale reviews without automatically replaying uncertain writes.
Bind the actual assessment result to the existing approval runtime and a real
authenticated reviewer. An approval from a superseded proposal cannot authorize
a newer diff. Do not send a live event into an unfinished approval handoff.
