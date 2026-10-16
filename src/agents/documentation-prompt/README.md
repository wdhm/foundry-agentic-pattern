# Documentation prompt agent: gap analysis (#13)

> **Reference during migration:** P1 selected the hosted `documentation-agent`
> as the main runtime on 2026-10-16. This working prompt-agent implementation
> is retained, not removed or redeployed. See
> [ADR 0024](../../../docs/adr/0024-hosted-documentation-runtime.md).

This is the **MVP assessment workflow on the existing Foundry prompt agent
`doc-agent`**, not a new hosted app. Foundry runs the tool loop. P2's existing
`knowledge`, `github` and `ado` integrations supply the standard, pinned source
files, current wiki and work items.

| File | Purpose |
|---|---|
| `../documentation-agent/app/prompts/gap-analysis-v1.txt` | Shared assessment instructions, now owned and packaged by the hosted app |
| `../documentation-agent/app/policies/documentation-analysis-v1.txt` | Shared never-fabricate and proposal-only policy |
| `configure.py` | Preview or apply these files to a reviewed version of an existing prompt agent |

`configure.py` preserves model, tools, native approval settings, identity and
existing instructions. It adds a delimited assessment block; subsequent updates
replace only that block, preserving later instructions added by another track.
Identical configuration is a no-op. Prompt and policy hashes are recorded in
Foundry version metadata. It is configuration code, not an agent orchestrator.

## Configure

From the repository root, with the team Azure CLI account signed in:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[prompt,dev]"
.\.venv\Scripts\python.exe src\agents\documentation-prompt\configure.py `
  --project-endpoint <existing-project-endpoint> `
  --agent-name doc-agent --base-version <reviewed-latest-version>
```

Without `--apply`, this prints the proposed definition and makes no Azure changes.
Add `--apply` only after review to create a version. An outdated base version is
rejected. The published schema is still contract v1; the hosted v0 stub is unchanged.

## Assess, do not write

- Retrieve the standard through Foundry IQ and cite `DS-xx` rules in descriptions.
- Read individual integration files at the requested full Git SHA, and the current
  wiki/work-item versions through ADO.
- Return `AnalysisOutput`: findings, proposed changes, missing information and
  verbatim evidence excerpts. No wiki write approvals are submitted.
- For a code-change review, assess that change, not every unknown production detail.
  For a task requiring unavailable owner/security/operations facts,
  `insufficient_information` takes precedence over `gaps_found`.

The #12 `contracts.prompt` CLI remains a **no-tools** contract demonstration.
Use the existing [scenario checker](../../../evals/README.md) for this tool-enabled
assessment. See the [five-minute walkthrough](../../../docs/workshop/gap-analysis-guide.md).
