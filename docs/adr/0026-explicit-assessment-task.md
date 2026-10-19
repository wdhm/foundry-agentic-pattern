# 0026. Explicit task and scope for hosted assessment

- **Status:** Proposed
- **Date:** 2026-10-19
- **Deciders:** P1
- **Related:** [0010](0010-python-and-pydantic-contracts.md), [0023](0023-versioned-structured-output-contract.md), [0024](0024-hosted-documentation-runtime.md), #13

## Context

Hosted v6 receives AgentRequest v1 with source references but no assessment
question. During P1 acceptance on 2026-10-16, the missing-information scenario's
question (business owner, Security and Operations) never reached the model.
The change-review run found all three planted gaps but treated an unrequested
change-log date as blocking. Source access succeeded; task representation did not.

## Decision

- Add optional `task` to AgentRequest v1, with required `scope` and `question`
  when present. Scopes are `change_review` and `information_review`; questions
  must be nonblank strings of at most 8,000 characters.
- `change_review` requires changed paths and limits assessment to that change.
  `information_review` uses paths as source locations while answering the
  question's requested facts. Neither grants access to new sources or writes.
- Missing/null task retains the previous source-based review and is omitted
  when serializing. This is an additive receiver capability: the corrected
  runtime accepts existing requests unchanged. Contract `1.0.0` and output
  schemas are retained; no existing result field is redefined.
- **Forward compatibility is not claimed:** older strict runtimes reject the
  new field. Callers must select an artifact supporting `AssessmentTask` before
  sending it. Do not strip a nonempty task for an older runtime, because that
  silently loses the caller's intent. Application `0.4.0` and the new request
  schema identify this capability; hosted version 6 does not have it.
- Pass the task as request data through the existing model call, not by
  interpolating arbitrary question text into system instructions. Keep all
  existing repository, commit, wiki, work-item and no-write guards.
- Use a new versioned hosted prompt (`gap-analysis-v1.1.txt`). Preserve the
  earlier prompt file for the retained prompt-agent reference.
- For explicit tasks, `missing_information` is reserved for material unresolved
  facts in that task. Reject a result that contains such unknowns but reports
  any status other than `insufficient_information`. Do not rewrite statuses,
  remove unknowns, or infer the correct answer from scenario IDs or keywords.
- Supplied evaluation continues to disable tools. `request.task` and an outer
  evaluation task may coexist only if the questions are identical. Live
  evaluation carries the task inside the production request, not as an outer
  override. Legacy supplied tasks remain supported.

## Alternatives considered

| Option | Reason not chosen |
|---|---|
| Put the question in requested_by or documentation_standard_ref | Those fields are identity/reference data, not task intent |
| Guess the task from a commit, path or scenario ID | Couples runtime behaviour to test fixtures and fails for new tasks |
| Force every gap response to gaps_found | Hides genuine missing source information |
| Make task mandatory immediately | Breaks existing callers that still use source-based review |

## Consequences

The P1 examples now retain the exact existing scenario questions. P3 still owns
CLI flags and scenario-to-request mapping; none of those files or gold answers
are changed. The model still needs live acceptance: local doubles prove that
the question arrives intact, policy remains enforced and inconsistent output
is rejected, not that model reasoning passes the scenarios. No deployment,
identity, Toolbox, gateway, permissions or routing change is made here.
