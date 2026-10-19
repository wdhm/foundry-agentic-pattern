# Five-minute CLI trigger

The default manual trigger targets **hosted `documentation-agent` assessment**,
per [ADR 0024](../adr/0024-hosted-documentation-runtime.md). The CLI does not deploy
an image, create an agent version, change routing, grant permissions, repoint a
gateway or publish to Teams. Invoking an existing hosted version creates a fresh
version-bound session and can incur compute/model/tool charges; run only with
separate invocation approval.

## Prerequisites and input

Install Python 3.11+ and `python -m pip install -e ".[agent,prompt]"` in a virtual
environment. Existing Azure CLI authentication and read/invoke/model-read access
to the exact project are required; this command does not log in for you.

P1/P2 must have built/published the reviewed immutable container, configured and
deployed **assessment**, supplied the real toolbox and verified hosted identity
access. `agent.yaml`'s historical stub default is not an assessment. See the
[runtime guide](../../src/agents/documentation-agent/README.md) and
[release prerequisites](evaluation-release-guide.md).

Create an operator-reviewed artifact JSON (no credentials) with the strict
`tools.hosted.HostedArtifact` fields:

| Field | Review requirement |
|---|---|
| `image` | Actual registry/repository `@sha256:<64 lowercase hex>`; tags are rejected |
| `source_commit` | Full build source commit |
| `build_reference` | Build/publish evidence associating that source with the exact digest |
| `readiness_review_reference` | P1/P2 review of packaged runtime, settings, tools and access |
| `runtime_provenance` | Actual P1 `contracts.v1.Provenance`, including application version and instruction/policy hashes |

The CLI compares the active version's stable SDK definition, image, Responses
2.0.0 protocol, managed-identity settings, project and deployed model version.
It reuses P1's `AssessmentSettings` and `AssessmentAgent` instruction assembly
to verify expected provenance against locally installed reviewed code. Install
the runtime revision corresponding to the image, not an unrelated wheel.
The build reference is an operator attestation, not a registry signature:
the CLI cannot independently prove which source files an image contains.

After assessment deployment and invocation approval:

```powershell
documentation-trigger invoke `
  --project-endpoint "<existing-project-endpoint>" `
  --agent-version "<concrete-Foundry-version>" --model-version "<actual-model-revision>" `
  --artifact "<reviewed-hosted-artifact.json>" `
  --repo wdhm/foundry-agentic-pattern --commit ad623147fbb1eeb9a6423d437df199c91db15a9e `
  --path samples/sample-integration/config/settings.json `
  --path samples/sample-integration/src/order_sync.py `
  --wiki-page "/Order Sync/Overview" --work-item 1 `
  --documentation-standard-ref "<verified-documentation-standard-reference>" `
  --requested-by demo-reviewer
```

`--agent-name` defaults to `documentation-agent` for hosted mode. `--path`,
`--wiki-page`, `--work-item` and `--adr-ref` are repeatable; `--pr-reference`
is optional. Full Git SHA is mandatory. `--request-id` and `--correlation-id`
accept UUIDs; otherwise each invocation generates fresh IDs.

Task-aware runtime app `0.4.0` also supports paired `--task-question` and
`--task-scope change_review|information_review`, serialized as canonical
`request.task`. Omit both to preserve legacy source-based assessment.
`change_review` requires changed paths; `information_review` makes the missing-fact
intent explicit. Task text is a question/scope, never gold answers, source evidence
or write authorization. The CLI keeps P1's task validation and status precedence.

The actual model input is **only one bare AgentRequest v1 JSON user text**.
The CLI does not wrap it in a scenario prompt, source bundle, gold answer or
chat history, and does not attempt `tool_choice=none` to override P1's internal
Agent Framework loop. Only P1's configured read tools execute.

## Output and version identity

Stdout is one report containing real `run_id`/`response_ids`,
`agent_session_id`, exact Foundry `agent_version`, image/build/source lineage,
request/correlation IDs and the actual validated `result`.
`result` is already P1's `contracts.v1.AgentResult`: it is **not** reassembled
from `AnalysisOutput` or given invented caller provenance.

P1's `result.provenance.agent_version` is the **application version** (currently
`0.4.0`), not the Foundry version. Both identities are retained independently.
Request ID, Git evidence SHA and reviewed runtime provenance must match.
Failed/incomplete responses, invalid JSON, wrong version/correlation, refusals
and unexpected tools/approval requests exit nonzero without a success report.
The hosted CLI never resumes approvals or turns proposals into writes.

Each invocation explicitly creates a fresh session bound to the selected
version, GET-confirms its binding/readiness, then uses the agent's Responses
endpoint with `agent_session_id`. This **bypasses serving selection** and is not
named-endpoint serving-pin proof. Sessions do not migrate when routing changes.
Created sessions are retained; no implicit stop/delete or routing cleanup occurs.
Record their IDs and manage their lifecycle through a separately approved plan.

The report separately retains `session_version_indicator`, `outer_agent_reference`
and `version_evidence`. If the outer reference is absent, the report labels the
evidence `session_get_only`, not independent executing-image proof. If the outer
reference names another agent/version, the CLI logs both values and the real
session/response IDs on stderr, then exits nonzero without candidate-version
success. P1 reported session GET version 7 versus outer version 6 on 2026-10-19;
this branch tests that discrepancy offline and does not hide it behind matching
application provenance. No cloud reproduction or platform resolution is claimed.

This is a valid assessment smoke path when real P2 access is ready, not release
certification: P1's nested tool traces are not in outer Responses. The full
five-case gate remains blocked on **P3 adapter integration** of P1's separately
opted-in evaluation interface, isolated configuration/evaluator mappings and
trustworthy version evidence. Main's `contracts.evaluation` now supports supplied
sources and observed execution records, but ordinary assessment remains unchanged.
This CLI rejects evaluation/approval modes rather than silently enabling or
interpreting their envelopes as AgentResult. No live evaluator result is claimed here.

## Explicit prompt compatibility

The earlier behavior remains available by adding `--agent-kind prompt`.
`--agent-name` then defaults to `doc-agent`; `--artifact` is not used. Existing
request/model/version flags and `python -m tools.cli invoke` remain supported.
This secondary path uses project Responses `agent_reference.version`, validates
`AnalysisOutput`, and assembles caller-owned `AgentResult`. Its interactive
native MCP approval handling is unchanged: exact Approve/Reject, no automatic
approval, no noninteractive resume. It must not be confused with hosted write
enforcement. `documentation-prompt` is still the separate no-tools contract demo.

Historical prompt smoke on 2026-10-16 against `doc-agent:3` returned `gaps_found`:
run `resp_0c26cb44747c1c09006ad1d8edf2a48194b2b67d734931f75d`,
correlation `e94dcd51-52ca-4d43-8494-9a9eb34cb062`.
That remains prompt-only evidence, not a hosted baseline or release score.

Official sources:
[hosted session sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_sessions_crud.py),
[session Responses invocation](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/hosted_agents/sample_session_log_stream.py),
[session management](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-sessions).
