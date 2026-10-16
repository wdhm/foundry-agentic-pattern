# Hosted assessment deployment: preparation and gates

**Status, 2026-10-16: blocked before deployment.** This prepares the committed
P1 hosted runtime under [ADR 0024](../adr/0024-hosted-documentation-runtime.md).
It does not complete hosted source integration, approval enforcement, release
certification or Teams publication. No Azure mutations or remote invocations
were performed. The canonical, environment-specific plan is the deployment
owner's ignored `.azure/deployment-plan.md`; this guide contains no tenant IDs.

## Verified state and blockers

| Surface | Read-only result |
|---------|------------------|
| Source | Current main `1ddaec87a8cb5e50af38d817c44642378bc8f63f` |
| Hosted agent | `documentation-agent`, versions 1 and 2 active, latest 2 |
| Retained baseline | Version 2, historical stub application 0.1.0; not an assessment baseline |
| Retained image | Existing ACR digest recorded in [setup](../setup.md#hosted-contract-stub-p1-7), manifest still readable |
| Prompt reference | `doc-agent:3`, preserved |
| Both named endpoints | `@latest` / 100%, Responses, Entra, `not_published` |
| Toolbox | Successful `GET /toolboxes?api-version=v1` returned an empty list |
| Source connections | GitHub CustomKeys, IQ ProjectManagedIdentity, ADO AgenticIdentityToken; not themselves a toolbox |
| ADO gateway | Identity and blueprint still match the prompt agent, not hosted |
| Models | Existing `gpt-6-luna` revision `2026-09-22` and embedding retained |

Use authenticated WSL, not a stale Windows cache. The installed azd toolbox
command returned `WorkspaceNotFound`; that failure alone is not an empty
inventory. The successful `v1` REST GET provides the empty-inventory evidence.
Do not dump connection metadata, credentials or `azd env get-values` into logs.

Hosted model/session permissions can be supplied by platform defaults; an empty
Azure role listing is not proof of access denial. Conversely, connection presence
and a prompt-agent success do not prove hosted toolbox/source authentication.
Verify the actual hosted credential and each allowed read, without automatically
granting broader roles.

## Minimum P1/P2 integration

P2 must supply a versioned toolbox exposing exactly:

- `knowledge___knowledge_base_retrieve`
- `github___get_file_contents`
- `ado___wiki`
- `ado___wit_work_item`

P2 owns connection authentication, source access and hosted-compatible ADO
authorization. P1 owns compatibility of the real tool schemas/results with
the committed read guard and evidence parser. Standard retrieval is mandatory.
Git reads must use the requested repository and commit; ADO reads must remain
within the configured project/wiki and requested paths/work-item IDs.

Creating a toolbox is additional data-plane configuration, not an existing
resource discovered by this preparation. Verify whether existing IQ/GitHub
connections can be reused without changing the prompt agent. The current gateway
serves a single agent identity; running onboarding re-points it. Do not run
onboarding as an incidental deployment step.

If isolated hosted ADO access cannot reuse existing configuration safely, P2 must
propose a separately scoped gateway or explicitly coordinated identity transition.
That proposal needs its own resource/SKU/cost, consent, entitlement and permission
review. **Neither new infrastructure nor gateway repointing is approved here.**
The deployment owner must wait rather than downgrade to a stub.

## Container preparation

Build from the repository root, using the existing Dockerfile and explicit
`linux/amd64`. All three packages declared by `pyproject.toml` must be copied and
allowed by `.dockerignore`: `contracts`, `documentation_agent`, and `tools`.
The last package is required for wheel construction even though the hosted entry
point does not call the trigger CLI. Assessment prompt/policy files are package
data and must be present in the installed wheel.

The omitted `src/tools` failure was reproduced with the Docker COPY inputs.
The corrected inputs successfully built a wheel containing all packages and
assessment prompt/policy. A full local image build failed earlier in pip TLS
negotiation with the public package host. No credential-free mirror was configured.
A successful wheel build is **not** a successful image build or hosted smoke.
Resolve trusted package access locally; never disable TLS verification, pass
credentials in build arguments, or switch to billable Azure builds without approval.

Keep the existing container method, existing ACR and immutable image digest.
Do not provision another Foundry stack or switch to direct code deployment merely
because a generic guide recommends it. Keep build/config scratch ignored.

## Candidate configuration

The committed `agent.yaml` intentionally defaults to `DOCUMENTATION_MODE=stub`.
An assessment candidate needs all settings in the
[runtime guide](../../src/agents/documentation-agent/README.md#run-assessment-mode-after-p2-supplies-access):
assessment mode, managed identity, existing project endpoint, actual toolbox MCP
endpoint, existing chat deployment and its actual revision, exact ADO project/wiki,
`HOST=0.0.0.0`, and port 8088. Missing settings must fail, not fall back.

The stable Projects SDK uses `container_configuration.image` and
`protocol_versions` for hosted definitions; the legacy flat `agent.yaml` template
is not a serialized stable-SDK payload. Verify the exact installed SDK/azd schema
and resulting environment before creating a version.

## Required approval and serving isolation

The creator must obtain exact subscription/location and bounded plan approval,
plus a real hold covering P1/P2, portal writers, CI and deployment hooks. No
coordination or approval is inferred from silence. Prior approval to pin prompt
version 3 does not authorize any hosted selector change.

Before candidate creation, explicitly review retained hosted version `G` (version
2 is the current historical stub candidate), refresh its active state/image and
preserve identity, protocols, authorization and complete endpoint configuration.
With explicit hosted approval, pin `G` at 100%, read back unchanged configuration
and verify a fresh named-serving session if that probe is approved. There is no
verified atomic `If-Match` contract; stop on unexpected state or a missing hold.
See the [serving runbook](release-rollback-guide.md#candidate-isolation-and-release-sequence).

**Inspect deployment hooks before using azd.** `azd ai agent endpoint update`
PATCHes manifest `agentEndpoint`/`agentCard`. Public azd source also performs
post-deploy endpoint patches when those fields are supplied:
[Deploy / patchAgentEndpointFields](https://github.com/Azure/azure-dev/blob/1bd2ca4699c7b1f371db85dd867f18aa4fbc4730/cli/azd/extensions/azure.ai.agents/internal/project/service_target_agent.go).
This source review does not establish the installed `agents1.0.0-beta.18`
binary's exact behavior. Confirm the chosen version, resolved service/reference
and all hooks preserve `G` before deploy; do not trust generic deploy success.
No executable deployment configuration was generated during preparation.

After integration, image and isolation gates clear, complete `azure-prepare`,
set the local plan to `Ready for Validation`, invoke `azure-validate` and capture
actual proof. Only then invoke `azure-deploy` for the approved immutable image and
one candidate. Never manually claim `Validated`. Preserve previous images and
versions; no automatic delete, rollback, promotion, traffic split or publication.

## Cost and capacity boundary

The proposed deployment reuses Foundry, ACR, chat/embedding, Search, gateway and
native `appi-foundry-agentic` / `log-foundry-agentic`; it includes no ARM
provisioning, new model capacity or evaluator deployment. No Azure-side build,
eval suite, write-tool execution or Teams/Bot is included.

Future candidate storage, hosted CPU/memory while active (including session idle),
one model-backed smoke, source retrieval and telemetry can incur charges. The
existing 0.5-vCPU/1-GiB size is a supported tier, not verified spare capacity.
A separately approved named-serving baseline probe also consumes hosted compute.
Any additional isolated gateway requires separate cost/resource approval.

The quota CLI returned `BadRequest` for CognitiveServices. Provider-specific
regional usages did not report hosted compute quota; existing chat allocation
also exceeded the returned regional limit. No quota/capacity change was made.
Do not report capacity validation as passed or alter the working model to repair
that pre-existing discrepancy.

## Meaningful smoke and evidence

After approval, submit exactly one user text containing a bare `AgentRequest` v1,
using the pinned fictional integration in
[`examples/assessment-request.json`](../../src/agents/documentation-agent/examples/assessment-request.json).
Generate fresh request/correlation IDs locally. It targets the sample at commit
`ad623147fbb1eeb9a6423d437df199c91db15a9e`, wiki `/Order Sync/Overview` and
work-item 1. Verify these sources are accessible without expanding the allowlist.
Do not attach a snapshot envelope or treat `tool_choice=none` as this tool-backed
assessment.

Create a fresh session explicitly bound to returned candidate `C`; require its
`version_indicator` to identify `C`, then invoke Responses using that session ID.
Require active readiness, exact digest/configuration, terminal `completed`,
schema-valid `AgentResult` v1, matching request ID, app provenance **0.2.0**,
actual model revision and prompt/policy hashes. Record the concrete Foundry
version separately from the application version.

Version-specific sessions bypass the named serving selector. Candidate success
is not named-serving, promotion or Teams proof. Re-read serving configuration
and require it still points to `G`. The nested read guard checks evidence, but
outer Responses does not export nested tool calls/schemas needed for release
tool-accuracy certification. Record available hosted traces and missing spans;
prompt traces are not hosted evidence.

Route Foundry's post-deploy evaluation-suite choice to the creator. Do not
generate synthetic data, run a suite or provision a judge without separate
approval. End with the exact artifact/version/session, preserved selector,
limitations, consumption/resource changes and cleanup needs; open a reviewable
PR, not an automatic merge.
