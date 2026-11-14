# ADR 0028: Opt-in A2A architecture visualization specialist

- **Status:** Proposed
- **Date:** 2026-11-13

## Context

The merge-triggered Documentation Agent already owns controlled investigation,
standard-based assessment, prose proposals and the Teams approval workflow.
We want to demonstrate collaboration with an independently managed specialist
while improving the integration wiki, without splitting existing authoring logic.

## Decision

Add a disabled-by-default A2A 1.0 consultation after successful assessment.
A separately configured prompt agent owns organization visualization instructions
and examples. It receives captured implementation/wiki sources, not tools or
credentials. It decides whether the existing architecture diagram can stay,
needs an update, is absent, or cannot be assessed from available evidence.

The host validates the returned evidence-linked graph and renders conservative
Mermaid for a single reserved wiki section. Both diagram and prose remain one
human-reviewed proposal. Publication authority and source guards are unchanged.

Use organization guidelines in the specialist's versioned instructions initially,
with no shared knowledge/tool connection. Keep the existing documentation
standard with the Documentation Agent. Scope is one integration, not the Foundry
solution's infrastructure.

## Alternatives considered

- Let the existing agent draw: simpler, but does not demonstrate independent
  policy ownership and A2A.
- Move all documentation authoring to another agent: changes the existing
  assessment responsibility unnecessarily.
- Delegate only commits classified as large: commit size does not establish
  diagram relevance and risks skipping meaningful changes.
- Accept arbitrary Mermaid from the model: more expressive but harder to enforce
  safe, consistent, target-compatible rendering.

## Consequences

Adds a remote dependency, latency and source sharing on enabled runs. Failed
consultations fail explicitly; insufficient context is surfaced without rewriting
the old diagram. The specialist can be independently reused and released, but
independence is a deployment/ownership decision, not a consequence of two files.

The optional visualization receipt extends enabled AgentResult v1 responses;
strict external consumers require the updated schema before opt-in. Disabled
response shapes remain unchanged. Card version is not a deployment-version pin.
Evidence quotation checks do not replace semantic evaluation or human approval.

This change is local only. Remote deployment, identity grants, organizational
policy approval, model quality and actual wiki rendering acceptance are separate.

See the [implementation guide](../../src/agents/visualization-agent/README.md).
