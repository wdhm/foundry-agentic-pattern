# src/contracts/

The **agent contract**: Pydantic models for `AgentRequest` and `AgentResult`. These models are the single source of truth. JSON Schema is generated from them and published alongside, so that non-Python callers (GitHub Actions, Teams adapters, evaluators) can validate payloads ([ADR 0010](../../docs/adr/0010-python-and-pydantic-contracts.md)).

> Placeholder. Implementation starts in **M1**.

## Planned shape (indicative)

**`AgentRequest`**
- `contract_version`
- `request_id`, `correlation_id`
- `trigger` (`github_pr` | `cli` | …) and `requested_by`
- `subject`: repo, commit SHA, changed paths, PR reference
- `context`: wiki page path(s), work item IDs, ADR references
- `documentation_standard_ref`

**`AgentResult`**
- `contract_version`, `request_id`
- `documentation_status` (e.g. `up_to_date` | `gaps_found` | `insufficient_information`)
- `findings[]`: `category`, `severity`, `description`, `evidence_refs[]`
- `proposed_changes[]`: target page/section and the proposed content
- `missing_information[]`: what is missing and where it was expected to be. The agent never fabricates ("Information missing").
- `evidence[]`: source type, URI, **exact version** (commit SHA / wiki page version / work item revision) and excerpt
- `confidence`
- `requires_human_review`
- `provenance`: agent name/version, model, prompt version, policy version, contract version

## Rules
- Breaking changes bump `contract_version` and require an ADR.
- Generated JSON Schema is committed and checked in CI. A schema that drifts from the models fails the build.

**Owner:** P1 (Agent architecture)
