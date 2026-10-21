# 0027. Add an opt-in AI gateway without changing live routes

- **Status:** Proposed; repository implementation for review, no deployment authorization
- **Date:** 2026-10-21
- **Related:** [0014](0014-infrastructure-scope.md), [0021](0021-agent-user-and-ado-mcp-gateway.md), [0022](0022-mvp-scope-platform-first.md), [0024](0024-hosted-documentation-runtime.md)

## Context

The user explicitly requested an AI gateway to govern models, tools and agents,
reopening the earlier MVP slides-only disposition. A10 uses Foundry hosted
Responses and Activity, Agent Framework model calls, a versioned read Toolbox,
the existing ADO identity gateway, and separate exact-call approved writes.
These paths have different identities and session/approval constraints.

## Decision

Add independently opt-in APIM routes for model inference and read-Toolbox MCP
transport, with direct mode unchanged by default. Reuse the pinned SDK and
existing Toolbox/ADO identity chain. Configure an existing APIM instance with
explicit caller identity validation, model allowlisting, usage/request limits,
unbuffered transport and body-free API diagnostics. Do not provision a service
or grant identities/roles automatically.

Add a separate optional, identity-bound named-agent `POST /responses` ingress
route for the version-bound hosted assessment CLI. Use the supported SDK base-URL
override while retaining the original bearer provider and agent feature headers.
Keep session creation and GET-confirmed concrete version checks direct; never
replace version evidence with a gateway-route claim. The initial omission of
agent Responses ingress was staging, not a technical compatibility blocker.

Keep Teams Activity, pipeline push transport, session control, selectors
and approved write calls direct. Do not claim fleet-wide agent governance or
that model routing also governs Foundry service-side evaluators. Preserve
evidence, version pins, source guards and approval/unknown-outcome semantics.
No semantic caching, automatic fallback, body rewriting or write retries.

The [integration guide](../ai-gateway.md) defines coverage, exact configuration,
identity mapping, observability, deployment review and rollback. Existing
Foundry-native AI gateway association remains a separately reviewed alternative,
not a live switch authorized by this decision.

## Alternatives considered

- **Native Foundry AI gateway only:** standard platform option, but project
  association would change live routes. Not executed; requires separate scope/
  coverage verification for this hosted runtime and its tools.
- **Proxy every project/agent endpoint:** conflates model APIs, version/session
  control and Activity ingress. Instead, expose only the named assessment
  Responses operation, with required session ID and no approval input arrays.
- **Replace the ADO gateway or approvals:** loses delegated identity/exact-call
  controls; APIM is complementary, not a replacement.

## Consequences

Reviewers get a small, reversible repository integration, not another agent
framework. Gateway failures surface rather than bypass controls. Direct access
remains possible, so this is not a non-bypassable security perimeter. APIM's
identity, policy, deployment/version mapping, SKU/cost and transport behavior
require isolated operator validation before enabling traffic. No live limit,
cost attribution or policy-enforcement claim follows from local tests.
