# Agent release and rollback: capability check and runbook

**P3, 2026-10-16.** Bounded read-only assessment for [#4](https://github.com/wdhm/foundry-agentic-pattern/issues/4), informing [#27](https://github.com/wdhm/foundry-agentic-pattern/issues/27) and [#34](https://github.com/wdhm/foundry-agentic-pattern/issues/34). P3 accepted the platform-first MVP on this date; the older P3 proposal labels in [ADR 0022](../adr/0022-mvp-scope-platform-first.md) are not a blocker. This guide does not change P1 scope or implement the release workflow.

**Decision:** design for one concrete version at **100%**, pinned **before** candidate creation. Do not implement 50/50 canary routing. Selector updates and channel publication are documented capabilities, **not live-verified operations**. No versions, sessions, endpoints, Bot resources, role assignments or channel publications were created; no invocations, traffic changes, gateway changes or monitoring changes were performed. The full #4 spike and #34's live rollback in under two minutes remain open.

## Read-only evidence

WSL Ubuntu Azure CLI **2.80.0**, using its existing authentication, successfully read the shared Sweden Central account and project on 2026-10-16. Windows Azure credentials were not used. IDs and tokens are intentionally omitted.

| Surface | Observed result |
|---|---|
| Account / project | `foundry-agentic-R8N3LD` / `proj-agentic`; account location `swedencentral`, public network access `Enabled` |
| Prompt agent `doc-agent` | Versions `1`, `2`, `3` report `active`; latest `3`; model deployment `gpt-6-luna`, model version `2026-09-22`, deployment `Succeeded` |
| Hosted agent `documentation-agent` | Versions `1`, `2` report `active`; latest `2`; separate P1 contract stub, not the prompt-agent workshop implementation |
| Hosted v2 image | `acrfoundryagenticr8n3ld.azurecr.io/documentation-agent@sha256:0ea1b08788643623e49ee75ab7e7013e3103ed8d551072461e8102eb39cc0220` |
| Both agent endpoint configurations | One `FixedRatio` rule: `agent_version: "@latest"`, `traffic_percentage: 100`; `responses` only; `Entra` authorization; `publish_approval_status: "not_published"` |
| Agent identities | Both agents have non-null `instance_identity.client_id`; no legacy identity migration was attempted |
| Publishing infrastructure | `Microsoft.BotService` provider `Registered`; **zero** `Microsoft.BotService/botServices` resources listed in the workshop resource group (not a tenant-wide inventory) |
| Current operator permissions | Inherited subscription `Owner` and account-level `Foundry User`; sufficient documented role coverage, not proof that a write or tenant policy permits publishing |

The live agent GETs prove management API access and configured endpoints, **not** successful Responses invocations or Teams delivery. `active` means version readiness, not "selected for production." Neither latest version is an eval-certified production baseline merely because it is active. The hosted stub does not reason over sources or perform wiki writes; application version `0.1.0` is not Foundry version `2` ([runtime guide](../../src/agents/documentation-agent/README.md), [deployment record](../setup.md#hosted-contract-stub-p1-7)).

### Repeat the safe checks

Run in the already-authenticated **WSL Bash** shell. These commands only read agent metadata:

```bash
PROJECT_ENDPOINT="https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic"
for AGENT in doc-agent documentation-agent; do
  az rest --method GET --resource https://ai.azure.com \
    --url "${PROJECT_ENDPOINT}/agents/${AGENT}?api-version=v1" \
    --query '[name,versions.latest.version,agent_endpoint]'
  az rest --method GET --resource https://ai.azure.com \
    --url "${PROJECT_ENDPOINT}/agents/${AGENT}/versions?api-version=v1" \
    --query 'data[].[version,status,definition.kind]'
done
```

Re-read immediately before any approved release; never hard-code today's latest versions as future rollback targets. Do not print access tokens or commit full agent definitions.

## Exact API contract and boundaries

Current [endpoint configuration](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-agent) and [hosted management](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent) documentation use the **project** base URL above, `api-version=v1`, and Microsoft Entra tokens for audience **`https://ai.azure.com`** (`--resource` is required with `az rest`).

| Operation relative to project endpoint | Meaning / verification |
|---|---|
| `GET /agents`, `GET /agents/{name}`, `GET /agents/{name}/versions`, `GET /agents/{name}/versions/{version}` | Inspect identity, endpoint, immutable version and readiness. List/get/version-list succeeded here; no SDK inference is needed. |
| `POST /agents/{name}/versions` | Create an immutable definition snapshot: prompt instructions/model/tools or a hosted container/configuration. **Not promotion by itself when pinned; potentially immediate exposure when following latest.** Not executed. |
| `PATCH /agents/{name}` | Change `agent_endpoint.version_selector` on the named agent; no separate endpoint creation or channel republish is needed in the new object model. Documented, not executed. |
| `POST /agents/{name}/microsoft365/publish` | Publish the stable endpoint to M365/Teams. Separate from creating an agent version or selecting the serving version. Documented, not executed. |

The two agent types share the **agent endpoint configuration** surface, not their runtime/deployment definitions. Do not use historical Agent Application/deployment selectors, start/stop operations, or hosted container settings as prompt-agent publish APIs. The [migration guide](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications) explains the distinction; its older "no public publish API" statement conflicts with the newer dedicated REST publishing guide below.

### Pin, promote and roll back

**Approval required; HTTP template only, not executed.** Substitute a reviewed agent name and concrete version `G` (the retained good version) or `C` (the exact passing candidate). Use the same operation for initial pin, promotion and rollback:

```http
PATCH {PROJECT_ENDPOINT}/agents/{AGENT}?api-version=v1
Authorization: Bearer {token-for-https://ai.azure.com}
Content-Type: application/merge-patch+json

{
  "agent_endpoint": {
    "version_selector": {
      "version_selection_rules": [
        {
          "type": "FixedRatio",
          "agent_version": "{G-or-C}",
          "traffic_percentage": 100
        }
      ]
    }
  }
}
```

`G` and `C` are strings returned by the version API, **not** model versions, image tags, `appVersion`, `latest` or `@latest`. Send only the selector when changing routing; read back and compare the rest of the endpoint. If separately changing `protocol_configuration` or `authorization_schemes`, include every existing entry that must remain: the publishing guide warns those collections are replaced.

**Canary is blocked by conflicting official guidance.** [Manage hosted agents: routing](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent#configure-agent-endpoint-routing) explicitly says traffic splitting is unsupported and requires one rule at 100%. The [azd production guide](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-production#roll-out-a-production-version-gradually) nevertheless shows multiple 90/10 and 50/50 rules. The general configuration page documents latest-or-pinned routing. The array shape and `FixedRatio` name do not prove canary support. Use the conservative single-version contract for either agent; obtain Microsoft clarification before any multi-rule probe. No routing PATCH, including a 100% pin, was validated against this deployment.

### Candidate isolation and release sequence

1. **Record serving version `G`, not just latest.** Read the selector and the referenced version, preserve the complete endpoint configuration, artifact/source revision and model deployment version. With today's `@latest`, resolve the concrete version and agree a good baseline first. Serialize all agent version creators and selector writers, including portal users; recheck state before each write.
2. **Pin `G` and verify the readback before creating `C`.** Also verify a fresh consumer invocation still uses `G`. Abort if pinning is unavailable or another writer changed state. A workflow that creates a version and only then runs evals is unsafe while routing follows latest. Review azd endpoint settings/hooks so deployment cannot overwrite the pin.
3. **Create and capture candidate `C`, then await `active`.** Do not resolve latest again for the eval or promotion. Confirm the exact definition/image and dependencies. Drafts are not the safety mechanism: the hosted guide warns that `draft: true` can create a normal release if the subscription is not enabled.
4. **Evaluate `C` explicitly, without changing the stable selector.** For the **prompt agent**, the project Responses API supports `agent_reference: {"type":"agent_reference","name":"doc-agent","version":"C"}`; this is the existing [prompt contract caller](../../src/contracts/prompt.py), not a hosted deployment selector. Use assessment-only inputs and no write-tool approvals. For a **hosted candidate**, create a session with the concrete version body below, then invoke Responses with its returned `agent_session_id`. This is a separate P1 stub/contract test, not a substitute for prompt-agent evals.
5. **Fail closed.** A failed eval, invalid contract, incomplete response, tool error, readiness timeout or missing evidence leaves the selector on `G` and the release failed. Do not publish or promote `C`. This is **prevented promotion**, not evidence that rollback was exercised. Passing one no-tools contract check is not a complete quality gate.
6. **Approve and promote `C` at 100%.** First ensure production still points to `G`, `C` is still active and the eval result belongs to that exact artifact/version. PATCH only the selector, read it back, and verify a fresh non-overridden consumer session. Save the before/after selector and trace/version evidence.
7. **Roll back to `G` if production checks fail.** Apply the same PATCH with `G`, read back and verify a fresh non-overridden session against `G`. Keep versions/images available. Hosted sessions bind their version at creation: existing sessions do **not** migrate on selector changes. Do not delete versions or claim a selector change undoes tool writes or restores conversation state.

Hosted candidate test contract, from [session management](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-sessions#create-a-session-explicitly-advanced); **requires separate invocation/compute approval and was not executed**:

```http
POST {PROJECT_ENDPOINT}/agents/documentation-agent/endpoint/sessions?api-version=v1
Authorization: Bearer {token-for-https://ai.azure.com}
Content-Type: application/json

{"version_indicator":{"type":"version_ref","agent_version":"{C}"}}
```

Then `POST /agents/documentation-agent/endpoint/protocols/openai/responses?api-version=v1` with `agent_session_id` in the JSON body and the valid stub request as `input`. For Invocations the session ID belongs in the query string instead; neither agent currently exposes Invocations. Check terminal protocol success and schema-valid output, not HTTP 200 alone. Hosted tests can start billable compute even when the payload is read-only.

## Sweden Central and M365/Teams publication

[Hosted availability](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#limits-pricing-and-availability) includes **Sweden Central**; live hosted versions exist here. That does not prove channel delivery, tool approval UX, capacity for a new deployment, or M365 data residency.

Before any separately approved publish:

- Require **Foundry User** on the project (inherited account coverage exists for this operator) and **Azure Bot Service Contributor Role**, Contributor or Owner on the publishing resource group. Required Bot actions are `Microsoft.BotService/botServices/write` and `Microsoft.BotService/botServices/channels/write`. Azure Owner covers Bot management but is not a substitute for Foundry data-plane access. Verify the future CI principal independently; today's interactive role assignments do not establish its access.
- Require the Bot provider registration, the agent's own `instance_identity.client_id`, and an Azure Bot resource pointing to that agent's Activity Protocol route with a Teams channel. The [REST publishing guide](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network) specifies a single-tenant bot, `global` location and an F0 example. No Bot resource exists in this resource group, and creating one still requires approval.
- Verify tenant Teams/M365 access, enabled service plans, app policies, permitted data flows and the actual demo user's invocation permissions. These were **not** checked through Graph or Teams. "Just you" avoids the publication admin-approval step; it does not bypass policy or RBAC. End users do not need a Microsoft 365 Copilot license for Copilot Chat, but shared-tenant-data use can incur usage charges ([troubleshooting/licensing](https://learn.microsoft.com/azure/foundry/agents/how-to/troubleshoot-publish-copilot#resolve-runtime-issues)).
- Retain `responses` and `Entra`; publishing adds `activity` plus Bot authorization. **Just you** maps to REST `publishScope: "Shared"` and `BotServiceRbac`; `Personal` is also accepted as Shared. Organization scope is `Tenant` / `BotServiceTenant` and requires M365 admin approval. Do not select Tenant for the personal demo.

Portal path: agent **Publish > Teams and Microsoft Copilot**, after pinning and testing the active version. The equivalent documented REST operation is:

```http
POST {PROJECT_ENDPOINT}/agents/{AGENT}/microsoft365/publish?api-version=v1
Authorization: Bearer {token-for-https://ai.azure.com}
Content-Type: application/json

{
  "agentDisplayName": "{approved-display-name}",
  "botServiceArmId": "{approved-bot-arm-id}",
  "publishScope": "Shared",
  "publishAsAutopilot": false,
  "appVersion": "1.0.0",
  "shortDescription": "{approved-short-description}",
  "fullDescription": "{approved-description}",
  "developerName": "{approved-developer}",
  "developerWebsiteUrl": "{approved-https-url}",
  "privacyUrl": "{approved-https-privacy-url}",
  "termsOfUseUrl": "{approved-https-terms-url}"
}
```

**Documentation-only template; do not run without approval.** Success returns `titleId`. `appVersion` versions the channel package/metadata, not agent behavior. Updating the active agent selector is documented to change behavior without republishing. Metadata updates require a new package version. No public-network exception is needed for today's PNA-enabled account. If networking changes, stop: private projects require a reachable management client and the separately approved `activity.enable_m365_public_endpoint` exception, not enabling account-wide public access.

For hosted agents, Foundry bridges Responses to Activity; this does not make the JSON-only stub a natural-language assistant. Published channels do not support streaming responses or native citations; render evidence links in message text. For a new-session rollback check, use a new Copilot chat; the current Teams troubleshooting guide specifies `/foundry_new_preview` to reset the conversation (destructive to that conversation history). Preserve required evidence first. Verify agent-user/blueprint credentials and gateway access survive publication separately; do not re-onboard or repoint the gateway as part of a rollback test.

## Next approval and exit evidence

**Smallest next probe:** approve a coordinated, reversible **single-version routing test on the existing prompt agent only**, without creating versions or publishing. Record its current resolved serving version, pin that concrete version at 100%, GET/read back, and use an assessment-only no-tools invocation to verify a fresh consumer session. If that succeeds, separately approve switching between two reviewed existing versions and back, with fresh-session/trace evidence. Agree the final concrete serving pin; restoring `@latest` would reintroduce candidate exposure.

Only after that, authorize candidate creation/evaluation for #27; do not treat this guide or API permission as authorization. A separate channel probe needs approval for Bot creation/channel configuration, Shared publication and Teams sign-in/message tests. Record `titleId`, stable endpoint, effective identity/authorization, new-session version before/after rollback and elapsed time. Check licenses/policies and credential survival then. No approval exists for these changes in this assessment.

**Exit criteria:** #27's implementation can use the documented pin-before-create contract but cannot claim live promotion/rollback acceptance yet. #4 remains blocked on channel publication and end-to-end evidence, with its 50/50 step unsupported/conflicted. #34 remains unverified until a separately authorized timed rollback demonstrates **under 120 seconds**, correct fresh-session version, and trace/cost evidence; a fast PATCH or GET alone is insufficient.
