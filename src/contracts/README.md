# src/contracts/

The **agent contract**: Pydantic models for `AgentRequest` and `AgentResult`. These models are the single source of truth. JSON Schema is generated from them and published alongside, so that non-Python callers (GitHub Actions, Teams adapters, evaluators) can validate payloads ([ADR 0010](../../docs/adr/0010-python-and-pydantic-contracts.md)).

## Contract v0 (`0.1.0`)

The hosted demo keeps v0 unchanged. New prompt-agent work uses explicit imports
from `contracts.v1` (`1.0.0`); see [Contract v1](#contract-v1-100) below.

The walking-skeleton contract ([#6](https://github.com/wdhm/foundry-agentic-pattern/issues/6))
is implemented. The result contains only request correlation and provenance; it
does **not** claim to have analysed documentation. Findings, proposed changes,
evidence and review requirements are defined separately in v1 for
[#12](https://github.com/wdhm/foundry-agentic-pattern/issues/12).

Install from the repository root (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[agent,prompt,dev]"
```

Requires Python 3.11+ and Pydantic 2.
The `agent` and `prompt` extras enable both demos and project-wide type checking;
consumers needing only contracts can install the package without extras.

### Fields

| Model | Required fields | Optional fields |
|---|---|---|
| `AgentRequest` | `contract_version`, UUID `request_id` and `correlation_id`, `trigger`, `requested_by`, `subject`, `documentation_standard_ref` | `context` (defaults to empty lists) |
| `Subject` | `repo`, full 40-character hexadecimal `commit_sha` | `changed_paths` (empty list), `pr_reference` (null) |
| `RequestContext` | None | `wiki_page_paths`, positive integer `work_item_ids`, `adr_refs` (all empty lists) |
| `AgentResult` | `contract_version`, UUID `request_id`, `provenance` | None |
| `Provenance` | `agent_name`, `agent_version`, `model` (deployment name), `model_version`, `prompt_version`, `policy_version`, `contract_version` | None |

All models reject unknown fields. Text fields must contain a non-whitespace
character. Contract versions must explicitly be `0.1.0`, including provenance.
Trigger names are adapter-defined, not limited to GitHub or CLI.
Source references are identifiers, not resolved or fetched by this package.

### Python usage

```python
from uuid import uuid4

from contracts import CONTRACT_VERSION, AgentRequest, AgentResult, Provenance, Subject

request = AgentRequest(
    contract_version=CONTRACT_VERSION,
    request_id=uuid4(),
    correlation_id=uuid4(),
    trigger="cli",
    requested_by="demo-reviewer",
    subject=Subject(
        repo="example/sample-integration",
        commit_sha="a" * 40,  # Replace with the actual commit being analysed.
        changed_paths=["samples/sample-integration/config.json"],
    ),
    documentation_standard_ref="data/documentation-standard.md",
)
result = AgentResult(
    contract_version=CONTRACT_VERSION,
    request_id=request.request_id,
    provenance=Provenance(
        agent_name="documentation-agent",
        agent_version="1",
        model="demo-chat",
        model_version="demo-version",
        prompt_version="0.1.0",
        policy_version="0.1.0",
        contract_version=CONTRACT_VERSION,
    ),
)
payload = result.model_dump_json()
assert AgentResult.model_validate_json(payload) == result
```

Adapters should use `AgentRequest.model_validate_json(...)` for incoming JSON and
surface Pydantic `ValidationError` to the caller. The runtime must echo the input
`request_id`; matching a result to a request is the caller's responsibility.
Provenance must come from runtime configuration, not invented by the model.

### JSON Schema and local checks

Committed Draft 2020-12 schemas live in `schema/` and are also included in the
Python distribution. Non-Python consumers should enable UUID format validation
in their JSON Schema validator.

```powershell
.\.venv\Scripts\python.exe -m contracts.generate_schema
.\.venv\Scripts\python.exe -m contracts.generate_schema --check
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

Generation is deterministic. `--check` exits nonzero for missing or stale schemas
without writing files. Contract tests also check committed schemas for drift.
The confirmed MVP scope keeps these checks local; a separate CI pipeline is not
part of #12.

## Contract v1 (`1.0.0`)

```python
from contracts.v1 import AgentRequest, AgentResult, AnalysisOutput, Provenance, assemble_result

# Validate incoming JSON before invoking Foundry.
request = AgentRequest.model_validate_json(request_json)
# Validate the model response before presenting it as a successful result.
analysis = AnalysisOutput.model_validate_json(model_output_json)
# Metadata is supplied by the caller, never authored by the model.
result = assemble_result(request, analysis, provenance)
```

`provenance` is a validated `Provenance` constructed from the actual runtime and
deployment configuration, not an arbitrary dictionary of model-generated values.
The v1 request uses the same fields as v0 but requires `contract_version=1.0.0`.

| Analysis field | Meaning |
|---|---|
| `documentation_status` | `up_to_date`, `gaps_found`, or `insufficient_information` |
| `findings` | Category, severity, description and evidence IDs |
| `proposed_changes` | Target page, target section, proposed content and evidence IDs |
| `missing_information` | Description of what is unavailable and its expected source |
| `evidence` | Unique ID, source (`git`, `wiki`, `work_item`), HTTPS URI, exact version and excerpt |
| `confidence` | Finite number between 0 and 1 |
| `requires_human_review` | Review needed, **not** permission to write |

Every field is required; use empty arrays when appropriate. Findings and changes
must reference existing evidence. Git versions require full commit SHAs;
work items require positive revision numbers; wiki versions require nonblank,
non-moving ETags/versions. These checks validate shape and relationships, **not
whether the source exists or the excerpt is true**.

`up_to_date` requires evidence and no findings, changes or missing information.
`gaps_found` requires findings. `insufficient_information` requires a missing-information
entry. Proposed changes always require human review.

`AgentResult` adds `contract_version`, `request_id` and `provenance` to these
fields. Pydantic generates all three v1 schemas in `schema/v1/`; the generator
and `--check` process both v0 and v1. Cross-field semantic validators run in
Python and are not fully represented in JSON Schema.

See the [five-minute prompt-agent demo](../../docs/workshop/structured-output-guide.md)
and [ADR 0023](../../docs/adr/0023-versioned-structured-output-contract.md).

## Rules
- Breaking changes bump `contract_version` and require an ADR.
- JSON Schema is generated from Pydantic, never edited manually.

**Owner:** P1 (Agent architecture): John ([@johnsward](https://github.com/johnsward))
