# Architecture Visualization Agent (local implementation)

An independently configured **Foundry prompt agent** that reviews the integration
architecture diagram, not the documentation pipeline's architecture. It owns
`instructions.txt` and the fictional organization policy in `guidelines.txt`.
The Documentation Agent retains its existing source tools, documentation
standard, prose assessment, Teams flow and publishing authority.

**Status (2026-11-14):** `visualization-agent:1` has been created in `proj-agentic`
using the existing `gpt-6-luna` deployment. Its approved A2A 1.0 card is enabled
and verified. The hosted Documentation Agent remains served at version 36;
the specialist passed direct A2A create/keep smoke tests using the fictional sample
source. The visualization-enabled hosted candidate and live flow acceptance are pending.
This is not a claim that two agents improve accuracy.

## Code ownership

The specialist is a managed prompt agent, not a second Python server. Foundry
executes its model and instructions. The Python files named `visualization*` in
the hosted application are the **caller-side integration**, not the specialist's
implementation:

| Location | Responsibility |
|---|---|
| This directory | Specialist instructions, organization guidelines and prompt-definition builder |
| `documentation-agent/app/visualization_agent_client.py` | Authenticate and communicate with the remote specialist over A2A |
| `documentation-agent/app/visualization.py` | Prepare source context, validate the response and merge diagram proposals into the documentation result |
| `documentation-agent/app/visualization_settings.py` | Configure the hosted caller's endpoint, expected versions and wiki target |
| `src/contracts/visualization.py` | Shared handoff/output models and deterministic Mermaid rendering |

Keeping validation and proposal merging in the host preserves the existing
approval boundary. A prompt agent cannot execute these Python modules, and does
not receive the host's repository tools or publishing authority.

## Flow

1. The existing merge pipeline invokes the hosted Documentation Agent.
2. Its normal model/tool loop reads scoped code and wiki and drafts prose.
3. If enabled, application code always makes one A2A consultation after successful
   assessment. The model cannot silently skip it based on commit size.
4. The specialist compares the current diagram with the supplied implementation,
   using its own guidelines. It returns `keep`, `create`, `update`, or
   `insufficient_context`, with evidence and reasoning.
5. The host checks request/source hashes, guidelines version and citations, renders
   a restricted Mermaid graph, and adds a proposal for `## Architecture diagram`.
6. The existing draft, Teams review, human approval and conditional wiki update
   carry the combined proposal. Nothing here authorizes an extra write.

The same opt-in applies to direct assessment calls, not only pipeline calls.
Chat remains unchanged. Calls must include the configured target wiki in their
allowed source scope. Supplied-source evaluation refuses the opt-in rather than
silently evaluating only half the flow. Live-source evaluation includes the
specialist receipt, but does not capture the remote model's internal traces.

## Local prompt definition

Using the repository Python environment:

```powershell
python .\src\agents\visualization-agent\configure.py --model "<reviewed-model-deployment>"
```

This prints a prompt-agent definition and structured output schema. It does not
authenticate, contact Azure, write files or deploy. The specialist has no tools:
the initial organization guidelines are bundled in its own instructions, rather
than copied from the Documentation Agent's knowledge base. An architecture/platform
team can version these independently and later supply a dedicated knowledge source.
Changing guidance requires reviewing the expected guidelines and card versions.

Before any deployment, review the actual organization's policy, model choice,
data-sharing boundary and proposed agent card with its owner. Enable incoming
A2A separately and give only the required endpoint access to the hosted caller.
The client expects skill ID `architecture-visualization` and an A2A 1.0 JSONRPC
interface at the exact configured endpoint. Do not copy deployment values from
another checkout or enable this on a serving agent implicitly.

## Opt-in configuration

Leave `DOCUMENTATION_ENABLE_VISUALIZATION` unset or `false` for existing behavior.
For a future reviewed deployment, configure:

```text
DOCUMENTATION_ENABLE_VISUALIZATION=true
DOCUMENTATION_VISUALIZATION_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/a2a
DOCUMENTATION_VISUALIZATION_AGENT_NAME=<name-returned-in-agent-card>
DOCUMENTATION_VISUALIZATION_CARD_VERSION=<reviewed-card-version>
DOCUMENTATION_VISUALIZATION_GUIDELINES_VERSION=1.0.0
DOCUMENTATION_VISUALIZATION_TARGET_PAGE=/Order Sync/Overview
```

The existing `DOCUMENTATION_AUTH_MODE` selects Azure CLI credentials for local
development or managed identity for hosting. A token for
`https://ai.azure.com/.default` authenticates discovery and invocation.
Authentication and access must be configured on the target agent; there is no
anonymous fallback. Card/interface URLs cannot redirect credentials elsewhere.

Card version is a reviewed capability release label, **not proof of an immutable
Foundry deployment version**. The specialist owner must manage its release pin.
The response echoes the expected guidelines version, but that is not cryptographic
proof that a particular prompt was executed.

## Contracts and safeguards

The Pydantic contracts are in `src/contracts/visualization.py`; generated schemas
are in `src/contracts/schema/visualization/`.

- Handoff contains the task, commit-pinned subject, exact current diagram section,
  and captured Git/wiki/work-item source content, with URIs and versions. Knowledge
  tool output (the documentation standard) and credentials are not included.
  The remote agent receives source content, so deployment approval must authorize
  that data sharing even though the specialist has no repository access.
- The handoff is limited to 40 sources, 32,000 characters per source and 96,000
  serialized UTF-8 bytes overall. Oversized packages fail; they are not truncated.
  These are only the sources the investigator actually read, not a claim of full
  repository coverage or a before/after diff.
- The specialist returns a structured graph rather than executable Mermaid.
  Every node and connection references evidence. Citations are checked against
  actual reads, not trusted because another agent returned them.
- Rendering accepts only `graph LR`/`graph TB`, safe labels, rectangles, rounded
  rectangles, cylinders and labelled arrows (12 nodes/24 connections maximum).
  No arbitrary styling, directives, HTML, external links or click handlers.
  This enforces consistent notation, not arbitrary brand styling.
- `keep` leaves the diagram bytes unchanged. The prose agent is prohibited from
  proposing that section or a second Mermaid diagram. A conflicting proposal fails.
  Existing diagrams must live under the unique `## Architecture diagram` section;
  unsupported or ambiguous page layouts require manual review.
- `insufficient_context` preserves the old diagram and adds explicit missing
  information. Other independently valid prose changes can still be reviewed.
  A timeout, malformed response, wrong version, invalid citation or failed task
  fails the assessment instead of masquerading as `keep`.
- A2A uses authenticated v1.0 discovery and blocking `SendMessage` JSON-RPC.
  Only a completed task with one artifact, or a direct agent message, is accepted.
  There is a 90-second deadline within the existing overall assessment budget,
  a 128,000-byte response limit, and no automatic
  retry/resubmission, polling, file fetch or cross-request conversation reuse.
- The opt-in result includes a `visualization` receipt (decision, reason, card and
  guidelines versions, input hash). Disabled results omit it. Update strict
  external v1 consumers to the regenerated schema before enabling; older consumers
  that reject unknown properties will not accept this optional extension.
  Review notes include the receipt; the wiki contains the diagram, not audit data.

Matching a quotation proves its origin, not that it supports every architectural
claim. Semantic accuracy, completeness, remote-model behavior and actual Azure
DevOps rendering still need human/model-quality evaluation.

## Local validation

```powershell
python -m pytest tests\agents\test_visualization.py tests\agents\test_hosted_assessment.py tests\agents\test_push_flow.py tests\agents\test_wiki_page.py -q
python -m contracts.generate_schema --check
```

Offline cases exercise disabled behavior, all four decisions, evidence and request
binding, A2A v1 JSON-RPC messages/completed artifacts, failures, safe graph
rendering, and the pipeline-to-draft-to-human-approval path using fake sources and
a fake specialist. They do not invoke a live model or publish to a real wiki.

For live acceptance, include a structurally unchanged refactor (`keep`), an
evidence-backed new component/connection (`update`), missing diagram (`create`),
and inadequate sources (`insufficient_context`). A small change can invalidate a
diagram; a large refactor can leave it accurate. Start with one integration-level
diagram and do not invent complexity in the thin sample.

## References

- [Foundry incoming A2A and authentication](https://learn.microsoft.com/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint)
- [A2A 1.0 specification](https://a2a-protocol.org/v1.0.0/specification/)
- [Azure DevOps Mermaid support and limitations](https://learn.microsoft.com/azure/devops/project/wiki/markdown-guidance?view=azure-devops#work-with-mermaid-diagrams)

Azure DevOps renders Mermaid itself; embedding mermaid.js is unnecessary.
The conservative `graph` subset avoids the documented `flowchart` limitation.
The host writes a Mermaid fenced block inside the existing section composer.
