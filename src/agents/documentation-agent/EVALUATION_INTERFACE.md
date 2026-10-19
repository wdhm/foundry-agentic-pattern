# P1 hosted evaluation interface (#13)

**Implemented locally; not deployed or live-verified.** This is an application
interface for P3 to consume, not an evaluator, release gate or deployment workflow.
The hosted Python application runs the model directly. It never invokes the
`doc-agent` prompt agent.

## Modes and compatibility

| Runtime configuration | Request / response | Source behaviour |
|---|---|---|
| `DOCUMENTATION_MODE=stub` | Existing v0 contract | No model/tools |
| `DOCUMENTATION_MODE=assessment` | Existing bare v1 AgentRequest / AgentResult | Existing guarded live reads; no evidence export |
| `DOCUMENTATION_MODE=evaluation` **and** `DOCUMENTATION_ENABLE_EVALUATION=true` | EvaluationRequest / EvaluationResponse | Explicit live or supplied-source path |

The versioned evaluation interface is `1.0.0`; the application version is
`0.4.0`. AgentRequest/AgentResult remain contract `1.0.0`. The existing production
assessment endpoint rejects evaluation envelopes and cannot be switched into
snapshot mode by request content. Unknown fields are rejected.

Evaluation must be enabled by the operator, not by a caller request. It returns
source-bearing evidence and should only be deployed on a separately authorized
test version/session. **Do not enable it on the ordinary user-serving endpoint.**
Foundry authorization, exact version binding, serving isolation and artifact
publication remain P3 decisions. This code changes no Azure configuration.

## Transport

As with assessment, put one serialized input JSON object in Responses `input`:

```text
POST /responses
{ "input": "<EvaluationRequest JSON>", "stream": false, "store": false }
```

The successful output message contains one serialized `EvaluationResponse`:

```json
{
  "interface_version": "1.0.0",
  "result": {"...": "normal caller-owned AgentResult v1"},
  "execution": {"...": "observed application execution record"}
}
```

This sketch is not a fixture. Authoritative Pydantic models are in
`contracts.evaluation`; generated schemas are in `src/contracts/schema/evaluation/`.
Responses `status: failed`, refusal, timeout, malformed output, incomplete capture
or invalid evidence is an error, never a completed evaluation report. Streaming
also buffers until the final validated report; no partial unvalidated result is emitted.

## Live sources

```json
{
  "interface_version": "1.0.0",
  "source_mode": "live_sources",
  "request": {"...": "bare AgentRequest v1"}
}
```

No task override, standard override or snapshots are accepted in this mode.
The production request itself can contain the optional `request.task` object
on task-aware runtimes (application 0.4.0). That intent is forwarded unchanged to
the normal assessment path. Do not use the outer `task` in live mode.
It calls the same `AssessmentAgent.assess` path and read policy as ordinary
assessment. The model/tool behaviour is unchanged; capture is request-scoped.
Tool discovery and invocation failures remain failures.

The report contains:
- Actual discovered allowlisted function names, descriptions and input schemas.
- Successful tool calls in the shared `mcp_call` record shape: server label,
  tool name, JSON arguments and returned source content.
- Each nested SDK model request/response: messages, observed response ID/model,
  finish reason, token usage when provided, and timestamps.
- Exact assembled instructions, request/correlation IDs and a new execution ID.
- Platform call/session IDs when supplied by the actual hosting context; null
  locally or when absent. These are not invented Foundry response/version IDs.

The report is not an OTLP span export. It records observations at the SDK
boundary, not raw HTTP headers, hidden reasoning, raw provider objects or
connection credentials. Tool outputs can contain sensitive source data.
The returned `result.provenance` is the runtime's metadata; do not overwrite it
with the Foundry version. The client records the concrete deployment/version and
outer response/session identifiers separately.

## Supplied sources

```json
{
  "interface_version": "1.0.0",
  "source_mode": "supplied_sources",
  "request": {"...": "AgentRequest v1 with exact subject commit"},
  "task": "Optional original scenario question, without gold answers",
  "standard": {
    "content": "The exact documentation rules supplied for this case",
    "sha256": "<SHA-256 of UTF-8 content>"
  },
  "sources": [
    {
      "id": "config",
      "source": "git",
      "uri": "https://github.com/example/repo/blob/<sha>/settings.json",
      "availability": "available",
      "version": "<full commit SHA>",
      "content": "<exact source text>",
      "sha256": "<SHA-256 of UTF-8 content>"
    },
    {
      "id": "wiki",
      "source": "wiki",
      "uri": "https://dev.azure.com/example/wiki",
      "availability": "unavailable",
      "version": null,
      "content": null,
      "sha256": null
    }
  ]
}
```

The supplied array is the entire source allowlist. Omitted sources are not read.
For supplied mode, prefer `request.task` for explicit question/scope. The
legacy outer `task` is still supported when `request.task` is absent. If both
are supplied, their questions must be exactly identical; conflicting tasks are
rejected before model execution. Neither can enable tools.
An unavailable source has no content/version/digest and cannot be cited.
Available Git evidence must match the request SHA. Hashes are checked before
execution; they demonstrate bundle consistency, **not source authenticity**.
P3 must still verify its snapshots against the pinned source evidence.

The implementation:
1. Validates the bundle before any model call (20 sources, 500 KB total content).
2. Calls the configured model with the bundle and source-isolation instructions.
3. Uses **no toolbox, no tool discovery, no source-network client**, no prior
   conversation, `tools=[]`, `tool_choice=none`, and disables the function loop.
4. Rejects attempted model tool calls, incomplete/refused output and evidence
   not matching an available source URI/version/verbatim excerpt.
5. Returns the snapshots/standard as supplied-source context, not fabricated
   `mcp_call` observations. Tool schemas/calls are empty in this mode.

Model inference still needs the configured model/project credential and can
incur cost. The shared settings still include a toolbox endpoint for live mode,
but supplied mode never uses it. There is no URL/file downloader in this path.
If an explicit unavailable source exists, the result must report
`insufficient_information`.

## Handoff to P3 (no P3 code changed here)

| P3 prepared-case value | P1 interface value |
|---|---|
| Validated case request | `request` |
| `mode` | `source_mode` |
| Scenario question (not reference answer) | `task`, supplied mode only |
| Verified documentation rules | `standard.content` and its UTF-8 SHA-256 |
| Case-specific allowlisted snapshots | `sources` with unique IDs, exact content/version and SHA-256 |
| Known unavailable source | `availability=unavailable` with null content/version/digest |

Do not send `expected_status`, `gold`, `reference_answer`, baselines, thresholds
or score labels; the interface forbids those fields. This cannot detect answers
hidden inside arbitrary task text, so the evaluator adapter must keep labels out.
Snapshots may include adversarial instructions as test data; model compliance is
evaluated separately. Tools remain disabled regardless of embedded instructions.

For live evidence verification, the shared helper can consume
`{"output": report.execution.tool_calls}` with `report.result`. The P3 adapter
must review how model messages, tool schemas and actual calls map to the chosen
evaluator; no scorer compatibility or quality threshold is claimed here.

P3 PR #80's existing blockers are intentionally not edited or bypassed.
Integration requires a reviewed adapter change, artifact/provenance update,
isolated evaluation configuration and live validation. Ordinary assessment
smoke testing continues to use bare AgentRequest and bare AgentResult.

**Packaging handoff:** package data includes `schema/evaluation/*.json`.
The Docker build allowlist should include that directory when distributing
the generated schemas. P3's Dockerfile/build fix and deployment remain theirs;
no `.github`, `src/tools`, `evals`, `infra` or Docker build files were edited here.

## Verification boundary

Local tests exercise the real Agent Framework middleware/tool loop and Responses
HTTP wrapper with deterministic model/tool doubles. They cover source hash and
version mismatches, unavailable-source citations, forbidden extra fields,
tools-disabled construction, per-request isolation, transport round trips,
model input/output capture and existing v0/v1 compatibility.

No cloud invocation, version creation, gateway/identity switch, toolbox creation,
pipeline dispatch or Azure resource change was performed for this interface.
