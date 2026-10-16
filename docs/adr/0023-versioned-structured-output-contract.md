# 0023. Versioned structured output with caller-owned provenance

- **Status:** Proposed
- **Date:** 2026-10-13
- **Deciders:** P1
- **Related:** [0010](0010-python-and-pydantic-contracts.md), [0022](0022-mvp-scope-platform-first.md), #12

## Context

The v0 result only proves that the hosted stub can receive a request. The MVP
prompt agent needs findings, proposed changes, missing information and
versioned evidence. Adding required fields is a breaking contract change.
The model must not invent execution metadata such as its deployment version.

## Decision

- Add contract `1.0.0` under `contracts.v1`, with explicit v1 imports and
  schemas under `src/contracts/schema/v1/`.
- Keep existing `contracts` exports and unversioned schema files at `0.1.0`
  for the separately deployed hosted stub. Do not silently upgrade old messages.
- Define `AnalysisOutput` for model-authored fields and `AgentResult` for the
  complete envelope. Generate both from Pydantic.
- Attach the analysis schema to Foundry prompt-agent `text.format` with
  `json_schema` and `strict: true`. Preserve the original model, tools and
  approval configuration when creating a new version.
- The caller validates the output, copies the request ID and adds provenance.
  Agent name/version/model come from the selected Foundry version; model version
  is supplied from deployment configuration; the instructions are SHA-256 hashed.
- Python validators enforce evidence references, exact-version shapes and
  consistent statuses. JSON Schema alone cannot express all cross-field rules.
  Neither proves that evidence is truthful: retrieval and grounding belong to #13.
- The #12 CLI is a no-tools contract demo. It accepts only an honest
  insufficient-information result, not invented findings. It does not approve
  tools, write documents or build the analysis workflow.
- Per the confirmed MVP proposal, keep local schema drift checks and tests;
  do not introduce an additional CI pipeline in this change.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Replace v0 in place | Breaks the already-deployed hosted stub and its examples |
| Let the model return all provenance | Model-generated execution metadata is not trustworthy |
| Ask for JSON only in instructions | Does not use Foundry's native schema enforcement |

## Consequences

The hosted demonstration remains stable. The MVP gains a typed output boundary
without another infrastructure layer. Callers must validate with Pydantic after
generation; non-Python callers need equivalent semantic checks beyond JSON Schema.
Consumers using the prompt agent's latest version see structured analysis instead
of prose; version-pinned consumers can retain the earlier behaviour.
