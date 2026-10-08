# src/contracts/

The **agent contract**: Pydantic models for `AgentRequest` and `AgentResult`. These models are the single source of truth. JSON Schema is generated from them and published alongside, so that non-Python callers (GitHub Actions, Teams adapters, evaluators) can validate payloads ([ADR 0010](../../docs/adr/0010-python-and-pydantic-contracts.md)).

## Contract v0 (`0.1.0`)

The walking-skeleton contract ([#6](https://github.com/wdhm/foundry-agentic-pattern/issues/6))
is implemented. The result contains only request correlation and provenance; it
does **not** claim to have analysed documentation. Findings, proposed changes,
evidence and review requirements arrive with the version bump in
[#12](https://github.com/wdhm/foundry-agentic-pattern/issues/12).

Install from the repository root (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[agent,dev]"
```

Requires Python 3.11+ and Pydantic 2.
The `agent` extra enables the hosted-stub tests and project-wide type checking;
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
Wiring the standalone check into CI is tracked in #12.

## Rules
- Breaking changes bump `contract_version` and require an ADR.
- JSON Schema is generated from Pydantic, never edited manually.

**Owner:** P1 (Agent architecture): John ([@johnsward](https://github.com/johnsward))
