# src/agents/documentation-agent/

The **Documentation Agent**: a Microsoft Foundry **hosted agent** (container) built with the **Microsoft Agent Framework** ([ADR 0009](../../../docs/adr/0009-hosted-agent-runtime.md)).

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
.\.venv\Scripts\python.exe -m pip install -e ".[agent,dev]"
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
    -t documentation-agent:0.1.0 .
} else {
  docker build --platform linux/amd64 -f .\src\agents\documentation-agent\Dockerfile `
    -t documentation-agent:0.1.0 .
}
docker run --rm -p 127.0.0.1:8088:8088 documentation-agent:0.1.0
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

Versioned prompts and policies arrive with the analysis workflow (#13).

**Owner:** P1 (Agent architecture): John ([@johnsward](https://github.com/johnsward))
