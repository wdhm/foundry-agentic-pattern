# src/agents/documentation-agent/

The **Documentation Agent**: a Microsoft Foundry **hosted agent** (container) built with the **Microsoft Agent Framework** ([ADR 0009](../../../docs/adr/0009-hosted-agent-runtime.md)).

## Hosted assessment implementation (P1, #13)

### Task-aware assessment fix (local code, not deployed)

Application `0.4.0` accepts `request.task` with a `scope` and `question`. This
fixes the missing task channel found in hosted v6 acceptance. The existing
source references define what may be read; the task defines what question those
sources should answer. It cannot change tool permissions or authorize writes.

| Scope | Behaviour |
|---|---|
| `change_review` | Review documentation for explicit changed paths; do not invent a release/change-log task or let an unrequested date block the review |
| `information_review` | Check the specific requested facts; report unsupported facts in `missing_information` even if unrelated documentation gaps also exist |
| Omitted/null task | Previous source-based assessment; not a substitute for a caller's missing question |

The model receives the full validated request JSON. Question text is not injected
into system instructions. Versioned `app/prompts/gap-analysis-v1.1.txt` describes
scope and status precedence; the existing policy and read guards remain unchanged.
Contradictory task output fails explicitly; the app never forces a passing status.

Use `examples/assessment-request.json` for the original PR-change question and
`examples/information-review-request.json` for the original missing-information
question. They preserve the scenario questions and pinned sources, without
altering P3's datasets or scoring. Generate fresh request/correlation IDs for
live runs. The model still has only the allowed file-read tools; a question's
reference to a PR diff does not grant a new tool or permission.

**Deployment handoff:** hosted v6 does not accept the task field. P3 must deploy
the reviewed task-aware artifact and map scenario/CLI intent into `request.task`;
do not silently discard it. Re-run both original acceptance expectations on that
exact version before closing #13. Local fake-model tests are not quality acceptance.
No source connections, remote versions or serving settings changed in this fix.

The opt-in [P1 evaluation interface](EVALUATION_INTERFACE.md) adds controlled
source snapshots and request-correlated model/tool evidence for P3 integration.
It is local code only and disabled by default. Existing stub/assessment payloads
are unchanged. The interface is not a replacement for P3's release/evaluation
workflow and is not enabled on the deployed agent.

For the separate #1 approval experiment, see the
[native approval spike guide](../../../docs/workshop/hosted-approval-spike.md).
It has its own local-only entry point and a dummy state receipt; it does not
enable writes in assessment mode or change the deployed agent.

For #15, the opt-in [exact-call Toolbox approval runtime](TOOL_APPROVAL.md)
reuses the spike's native transport/state preconditions but dispatches an actual
configured tool after approval. It was deployed in v8 and reused in v13. Its policy pins one tool and
target. The `propose_result` adapter connects a selected v1 proposed change and
its evidence to approval when the configured tool supports section-scoped writes;
whole-page composition is deliberately not guessed. Teams publication and shared
permission changes are not included.

The opt-in [Teams approval card adapter](TEAMS_APPROVAL.md) adds a native Activity
handler alongside Responses, with server-bound Approve/Modify/Reject controls.
The opt-in [Azure Repos push flow](PUSH_FLOW.md) prepares main-snapshot assessment,
proactive notification and reviewer-owned approval handoff. The v21 deployment
and automatic Azure Pipeline run 2 demonstrated this flow through Teams Reject
on 2026-10-21. It remains sandbox-only and does not implement PR comments.
An optional merged-PR mode now prepares immutable Azure Repos draft links and
compact cards; it is local code pending coordinated deployment and pipeline permissions.
Its opt-in `compose_wiki_page` mode preserves the actual page and updates only
proposed sections, with separate diff/evidence notes and ETag-bound approval.
`approval/order-sync-policy.json` targets `/Order Sync/Overview`; the live sandbox
policy is not changed by adding this file. Real conditional-write acceptance is pending.
The selected demo publisher uses `draft_storage: wiki`: automatic draft-only writes
under `/Drafts/Order Sync`, followed by human approval of the actual page update.
It requires no Git draft-branch write permission. Draft and destination versions
are checked; draft pages remain after the decision.
It was deployed as v13 and selected on 2026-10-20. The user verified real Teams
cards, Reject, Modify, old-decision rejection and Approve; independent ADO readback
confirmed the approved sandbox content. See the guide for the recorded image,
source snapshot, evidence and remaining audit/concurrency limitations.

The main runtime is now the hosted Python app ([ADR 0024](../../../docs/adr/0024-hosted-documentation-runtime.md)).
Assessment mode is deployed as `documentation-agent:6` and verified end to end
against live tools through P2's read-only toolbox `documentation-agent-readonly`
([setup](../../../docs/setup.md#read-only-toolbox-and-hosted-assessment-p2-2026-10-16)).

| Mode | Input | Behaviour |
|---|---|---|
| `DOCUMENTATION_MODE=stub` (default) | Contract v0 | Existing deterministic #7 demo; no model or tool calls |
| `DOCUMENTATION_MODE=assessment` | Contract v1 | Direct Foundry model call through Agent Framework, read-only toolbox tools, validated result |
| `DOCUMENTATION_MODE=approval` plus explicit enable flag | Proposed content / native approval / modify / inspect | Separate exact-call approval runtime; requires a reviewed target policy and verified hosted actor |

The default remains stub for compatibility. Assessment mode fails startup if
required configuration is absent; it never silently falls back to a stub result.
It does **not** invoke `doc-agent` or forward to another prompt agent.

The optional [AI gateway integration](../../../docs/ai-gateway.md) can route
assessment/evaluation model calls and read-Toolbox traffic through APIM.
`DOCUMENTATION_MODEL_GATEWAY_ENDPOINT` and
`DOCUMENTATION_TOOLBOX_GATEWAY_ENDPOINT` are independent, disabled-by-default
settings; they do not replace source guards, evidence checks or version pins.
The hosted CLI can separately opt its named-agent Responses request into APIM;
session/version checks, Teams Activity and approved write calls stay direct.
No APIM deployment or live configuration change is included.

### Assessment flow

```text
AgentRequest v1 -> validate -> per-request model/tool loop
    -> read-only action guard -> P2 toolbox -> source reads
    -> validate AnalysisOutput and observed evidence -> AgentResult v1
```

Each invocation owns its clients, credentials and tool evidence; state is not
shared between requests. The model receives the versioned prompt/policy packaged
in `app/prompts/` and `app/policies/`. It produces only `AnalysisOutput`. The
runtime adds the input request ID, model configuration, application version
`0.4.0` (not the Foundry deployment version), and instruction/policy hashes.
No unvalidated model tokens are streamed to the caller.

The official `FoundryToolbox` adapter handles authentication and platform call-ID
forwarding. Credentials use managed identity by default; explicit `azure_cli`
mode is for local development. Tool/client failures, missing tools, refusals,
invalid output, unmatched evidence and a 180-second invocation timeout fail
explicitly, not as successful assessments.

### P2 integration inputs

P2 provides the toolbox `documentation-agent-readonly`
([`setup-toolbox.ps1`](../../../infra/scripts/setup-toolbox.ps1)) with these
exact exposed names:

| Tool | P1 runtime restriction |
|---|---|
| `knowledge___knowledge_base_retrieve` | Read the documentation standard; required before accepting any assessment |
| `github___get_file_contents` | Requested repository and exact commit SHA; explicit relative path |
| `ado___wiki` | `action=get_page`, configured project/wiki, requested page path |
| `ado___wit_work_item` | `action=get`, configured project, requested integer work-item ID |

### Azure Repos source support (opt-in)

On 2026-10-20 this support was deployed as non-serving assessment version 11
with read toolbox version 2. The single smoke test returned pinned repository
and wiki evidence, but failed session/outer version agreement (11 versus 8).
It is **not a certified hosted integration**; the serving approval endpoint
remains on version 8. See the [rollout record](../../../docs/workshop/azure-devops-workflow-guide.md#hosted-rollout-record-2026-10-20).

Set `DOCUMENTATION_ADO_ORGANIZATION` only after reviewing a new read-toolbox
version that adds `ado___repo_file`. Existing configurations retain exactly the
four tools above. The extra tool accepts only `action=get_content`, the requested
repository, configured organization/project, an explicit file path and the
request's full commit SHA with `versionType=Commit`. Branch reads and write
actions are rejected before dispatch. The returned embedded file resource must
match the repository, path and commit before it can become Git evidence.

Use [examples/azure-repos-request.json](examples/azure-repos-request.json) for the
fictional Azure Repos baseline; generate fresh request/correlation IDs for a
real invocation. The same bare v1 contract, CLI, assessment and proposal-only
boundary are retained. No evaluation gold is sent to the agent.

See the [Azure DevOps workflow guide](../../../docs/workshop/azure-devops-workflow-guide.md)
for the verified sample, source-tool discovery, identity/deployment gates and
the separate automatic-event/Teams work. A direct user-account file read is
not proof of hosted agent-user repository access.

The triple underscore is Foundry's MCP tool namespace separator. No write tools,
tool-search dispatchers, code execution, unknown tools or automatic approvals
are exposed. Function middleware checks actions **before** dispatch, so a
multi-action `wiki` tool cannot be used for updates. `never_require` applies only
to the filtered read tools; the runtime rejects write actions independently
of toolbox approval metadata. Enabling writes requires #15, not a configuration
toggle on this assessment runner.

P2 verified the hosted identity's model/tool permissions, connection
authentication and the ADO gateway transition; see
[setup](../../../docs/setup.md#read-only-toolbox-and-hosted-assessment-p2-2026-10-16).
The gateway serves one agent identity; do not run onboarding to switch it
without coordination.

Evidence verification reuses `contracts.evidence`, also used by the scenario
checker. It supports P2's documented Git `documents[].content`, wiki
`page`/`eTag`, and work-item `fields`/`rev` outputs. GitHub MCP returns the
file as an embedded text `resource`; `parse_read_result` maps it to
`documents[].content`. Unsupported evidence is rejected. This matches
actual source excerpts, not the truth of every generated inference.

### Run assessment mode after P2 supplies access

Install `.[agent,prompt,dev]` from the repo root. Set the environment explicitly;
the `.env.sample` is a reference and is **not loaded automatically**:

```powershell
$env:DOCUMENTATION_MODE = "assessment"
$env:DOCUMENTATION_AUTH_MODE = "azure_cli"
$env:DOCUMENTATION_PROJECT_ENDPOINT = "<existing-project-endpoint>"
$env:TOOLBOX_ENDPOINT = "<P2-toolbox-MCP-endpoint>"
$env:AZURE_AI_MODEL_DEPLOYMENT_NAME = "<existing-chat-deployment>"
$env:DOCUMENTATION_MODEL_VERSION = "<actual-deployed-model-version>"
$env:DOCUMENTATION_ADO_PROJECT = "<ADO-project>"
$env:DOCUMENTATION_ADO_WIKI = "<ADO-wiki>"
.\.venv\Scripts\python.exe -m documentation_agent.main
```

Invoke `/responses` as shown below, using `examples/assessment-request.json`
instead of the v0 example. That file targets the same pinned fictional sample
as the planted-gap scenario. The container needs these same values, but use
`DOCUMENTATION_AUTH_MODE=managed_identity` in Foundry. Replace placeholders
before deployment; do not commit credentials or add CLI credentials to an image.

`agent.yaml` intentionally remains a stub definition until the P2 configuration
and coordinated deployment are ready. No cloud assessment result is claimed.

### Local verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\agents\test_hosted_assessment.py
```

These checks exercise the HTTP wrapper and real Agent Framework tool middleware
with in-memory model/tool doubles: valid/invalid requests, writes blocked before
execution, pinned source access, output/evidence validation, timeout, streaming,
per-request isolation and resource cleanup. They are not a substitute for the
live hosted scenarios after P2 integration.

### Prepare #13 acceptance without touching P3's caller or gold

`documentation_agent.acceptance` is an offline helper for the two original live
cases, not an invocation client or a replacement evaluation gate. After P3 gives
you the concrete deployment version containing PR #84, prepare a **new** directory:

```powershell
# Replace 42 with the actual candidate version supplied by P3; it is not discovered here.
.\.venv\Scripts\python.exe -m documentation_agent.acceptance prepare `
  --agent-version 42 --output-dir .azure\acceptance-candidate
```

It verifies the P1 examples still match the canonical sources/questions, adds
the explicit scope, generates fresh request/correlation IDs and saves single-line
JSON requests plus a `prepared_not_run` manifest with scenario hashes. It does not
change datasets, thresholds, resources or sessions. A version entered here is
not deployment proof.

Invoke each request through the coordinated exact-version hosted path and save
raw output locally. Confirm the session version binding separately; application
version in `AgentResult` is not the Foundry deployment version. Then extract:

```powershell
.\.venv\Scripts\python.exe -m documentation_agent.acceptance extract `
  --request .azure\acceptance-candidate\order-sync-retry-request.json `
  --response .azure\acceptance-candidate\order-sync-retry-response.txt `
  --expected-app-version 0.4.0 `
  --output .azure\acceptance-candidate\order-sync-retry-result.json `
  --analysis-output .azure\acceptance-candidate\order-sync-retry-analysis.json

.\.venv\Scripts\python.exe evals\check_planted_gaps.py `
  --scenario evals\datasets\order-sync-retry.json `
  --result .azure\acceptance-candidate\order-sync-retry-analysis.json
```

Repeat with `order-sync-information-missing`. Extraction accepts Responses JSON
or azd SSE output, rejects failed/incomplete/approval output and wrong request or
application provenance, and produces both the full v1 result and the exact
analysis-only shape required by the existing checker. It never alters scores,
statuses or source evidence and refuses to overwrite old outputs.

The unchanged checker's saved-result path does not independently prove source
reads. Preserve raw outputs and session binding, keep the scenario hashes stable,
and complete the P3 gate for #13 closure. The known Markdown-backtick URL-host
false positive is not suppressed by this helper. Clean up only your own live
test sessions after the separately authorized invocation.

## M1 local stub (#7)

The same image is deployed as `documentation-agent` version **2** in the shared
Foundry project. Deployment and remote invocation instructions are recorded in
[the setup runbook](../../../docs/setup.md#hosted-contract-stub-p1-7).

The local stub validates an `AgentRequest` and returns the v0 `AgentResult`.
It subclasses Agent Framework's `BaseAgent` and uses the official
`ResponsesHostServer` hosting adapter. It does not call a model, read sources,
persist runs or execute tools. Model provenance is explicitly `not-invoked`;
model and prompt versions are `not-applicable`. The application version is
`0.1.0`, not a deployed Foundry version number.

### Run locally

From the repository root (PowerShell, Python 3.11+):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[agent,prompt,dev]"
.\.venv\Scripts\python.exe -m documentation_agent.main
```

The local server binds to `127.0.0.1:8088`. `PORT` overrides the port; `HOST`
overrides the interface. No Azure credentials or model deployment are needed
for this stub. Stop with Ctrl+C.

In a second terminal, from the repository root:

```powershell
$request = Get-Content .\src\agents\documentation-agent\examples\request.json -Raw
$body = @{ input = $request; stream = $false; store = $false } | ConvertTo-Json
$response = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8088/responses `
  -ContentType application/json -Body $body
$response.status
$response.output[0].content[0].text | ConvertFrom-Json
```

The example uses fictional references and a placeholder commit SHA; the stub
validates their shape without fetching them.

### Contract versus transport

Foundry's Responses API is the **transport**, not the agent contract:

```text
POST /responses
  { input: "<AgentRequest JSON>", stream: false, store: false }
       -> Agent Framework stub -> validate -> build AgentResult
  { status: "completed", output: [... text: "<AgentResult JSON>" ...] }
```

Supply exactly one user text message containing the request JSON per invocation.
Chat history, multiple text items, attachments and plain-language prompts are
not supported by the stub. The hosting adapter can stream the same JSON result,
but the non-streaming path above is simplest for the CLI.

An invalid contract produces a Responses envelope with `status: failed`,
an empty output and a descriptive `error.message`. The adapter currently labels
this `server_error`; HTTP 200 alone does **not** imply success. Callers must
check the response status before parsing output. Invalid values are omitted
from validation messages.

### Container and hosted definition

Build from the **repository root**, not the agent directory, because the image
also needs the shared contracts:

```powershell
$pipLine = python -m pip config list |
  Where-Object { $_ -match '^global\.index-url\s*=' } |
  Select-Object -First 1
if ($pipLine) {
  $pipIndex = ($pipLine -split '=', 2)[1].Trim(" '")
  docker build --platform linux/amd64 --build-arg "PIP_INDEX_URL=$pipIndex" `
    -f .\src\agents\documentation-agent\Dockerfile `
    -t documentation-agent:0.2.0 .
} else {
  docker build --platform linux/amd64 -f .\src\agents\documentation-agent\Dockerfile `
    -t documentation-agent:0.2.0 .
}
docker run --rm -p 127.0.0.1:8088:8088 documentation-agent:0.2.0
```

The image uses Python 3.13, runs as a non-root user and listens on port 8088.
Its build context includes all three packages declared in `pyproject.toml`
(`contracts`, `documentation_agent` and `tools`); omitting `src/tools` fails
the wheel build even though the hosted entry point does not use the trigger CLI.
The allowlist also includes declared contract schemas, including the opt-in
evaluation interface schemas; packaging them does not enable evaluation mode.
The explicit `linux/amd64` build target avoids producing an ARM64 image on
ARM-based development machines. Docker Desktop may use emulation for this build.
The root `.dockerignore` allowlists only build inputs, excluding credentials,
local configuration, virtual environments and Git history.
`PIP_INDEX_URL` is an optional build-only argument for environments using a
package mirror; it is not persisted as a container environment variable.
Use only a credential-free mirror URL here: build arguments can appear in build
logs and image metadata. Do not pass tokens or passwords as build arguments.

`agent.yaml` is a **hosted definition template**, not an automatic deployment
script. Before submitting it to Foundry, replace `${AGENT_IMAGE}` with an actual
registry image reference (prefer an immutable digest). It declares Responses
2.0.0 and the initial CPU/memory allocation. See
[HostedAgentDefinition](https://learn.microsoft.com/python/api/azure-ai-projects/azure.ai.projects.models.hostedagentdefinition?view=azure-python-preview).

Deployment is not performed automatically by these files. It requires an accessible registry
image and the existing shared Foundry project, with the necessary identity and
registry connection. Follow [the setup runbook](../../../docs/setup.md); do not
provision another Foundry project or roll out IaC during M1 (ADR 0020).

### Local checks

```powershell
.\.venv\Scripts\python.exe -m pytest tests\agents tests\contracts
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

The prerelease hosting adapter and framework core are pinned to the versions
used for this implementation. The adapter does not ship a `py.typed` marker, so
mypy skips that third-party module; application and contract code remain strict.

## Target responsibilities (M1/M2)
1. Accept an `AgentRequest` and nothing else. The agent is trigger-agnostic ([ADR 0006](../../../docs/adr/0006-sources-and-trigger.md)).
2. Retrieve stable knowledge from Foundry IQ, and versioned or volatile data through Toolbox live calls ([ADR 0011](../../../docs/adr/0011-knowledge-foundry-iq-and-toolbox.md)).
3. Perform a gap analysis against the documentation standard.
4. Return a schema-valid `AgentResult` in which every finding is backed by evidence at an exact version, and anything unknown is reported as **"Information missing"**.
5. Persist the run, the result and the review decision to Cosmos DB, and emit traces to Application Insights.
6. For an approved result, call the **approval-gated** wiki-write tool. The runtime pauses, collects the Teams decision, and resumes or rejects that exact tool call ([ADR 0008](../../../docs/adr/0008-human-in-the-loop-approval.md), [R1](../../../docs/risks.md#r1)).

## Layout
```text
documentation-agent/
├── Dockerfile
├── agent.yaml            # Hosted definition template; image needs replacement
├── app/                  # Deterministic Agent Framework stub and server
└── examples/
    └── request.json      # Fictional contract example
```

`app/assessment.py`, `app/read_policy.py` and `app/settings.py` implement
assessment mode; `app/prompts/` and `app/policies/` hold its versioned instructions.
Cosmos persistence and approval-gated writes above describe the original target,
not functionality implemented or reintroduced by #13.

**Owner:** P1 (Agent architecture): John ([@johnsward](https://github.com/johnsward))
