# src/agents/documentation-agent/

The **Documentation Agent**: a Microsoft Foundry **hosted agent** (container) built with the **Microsoft Agent Framework** ([ADR 0009](../../../docs/adr/0009-hosted-agent-runtime.md)).

## Hosted assessment implementation (P1, #13)

The opt-in [P1 evaluation interface](EVALUATION_INTERFACE.md) adds controlled
source snapshots and request-correlated model/tool evidence for P3 integration.
It is local code only and disabled by default. Existing stub/assessment payloads
are unchanged. The interface is not a replacement for P3's release/evaluation
workflow and is not enabled on the deployed agent.

For the separate #1 approval experiment, see the
[native approval spike guide](../../../docs/workshop/hosted-approval-spike.md).
It has its own local-only entry point and a dummy state receipt; it does not
enable writes in assessment mode or change the deployed agent.

The main runtime is now the hosted Python app ([ADR 0024](../../../docs/adr/0024-hosted-documentation-runtime.md)).
Its assessment path is implemented locally, but **not deployed or verified
against live tools**. P2 must supply the toolbox endpoint and source access;
the shared gateway has not been switched away from the working prompt agent.

| Mode | Input | Behaviour |
|---|---|---|
| `DOCUMENTATION_MODE=stub` (default) | Contract v0 | Existing deterministic #7 demo; no model or tool calls |
| `DOCUMENTATION_MODE=assessment` | Contract v1 | Direct Foundry model call through Agent Framework, read-only toolbox tools, validated result |

The default remains stub for compatibility. Assessment mode fails startup if
required configuration is absent; it never silently falls back to a stub result.
It does **not** invoke `doc-agent` or forward to another prompt agent.

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
`0.3.0` (not the Foundry deployment version), and instruction/policy hashes.
No unvalidated model tokens are streamed to the caller.

The official `FoundryToolbox` adapter handles authentication and platform call-ID
forwarding. Credentials use managed identity by default; explicit `azure_cli`
mode is for local development. Tool/client failures, missing tools, refusals,
invalid output, unmatched evidence and a 180-second invocation timeout fail
explicitly, not as successful assessments.

### P2 integration inputs (not provisioned by this change)

P2 provides a toolbox in the existing project with these exact exposed names:

| Tool | P1 runtime restriction |
|---|---|
| `knowledge___knowledge_base_retrieve` | Read the documentation standard; required before accepting any assessment |
| `github___get_file_contents` | Requested repository and exact commit SHA; explicit relative path |
| `ado___wiki` | `action=get_page`, configured project/wiki, requested page path |
| `ado___wit_work_item` | `action=get`, configured project, requested integer work-item ID |

The triple underscore is Foundry's MCP tool namespace separator. No write tools,
tool-search dispatchers, code execution, unknown tools or automatic approvals
are exposed. Function middleware checks actions **before** dispatch, so a
multi-action `wiki` tool cannot be used for updates. `never_require` applies only
to the four filtered read tools; the runtime rejects write actions independently
of toolbox approval metadata. Enabling writes requires #15, not a configuration
toggle on this assessment runner.

P2 must also verify the hosted identity's model/tool permissions, existing
connection authentication, and the ADO gateway transition. The gateway serves
one agent identity; do not run onboarding to switch it without coordination.
This implementation creates no toolbox, connection or role assignment.

Evidence verification reuses `contracts.evidence`, also used by the scenario
checker. It supports P2's documented Git `documents[].content`, wiki
`page`/`eTag`, and work-item `fields`/`rev` outputs. Different output shapes must
be verified during integration; unsupported evidence is rejected. This matches
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
