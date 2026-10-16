# Integration Documentation Standard

**Version:** 1.0 · **Owner:** Integration Team (fictional) · **Applies to:** every integration page in the team wiki

This standard defines what an integration's wiki documentation must contain. The Documentation Agent uses it for gap analysis and for proposing updates. Replace this file with your own standard: it also sets the output language.

## Output language and tone

- **DS-01 Language.** Write documentation in **English**.
- **DS-02 Tone.** Use short, factual sentences in the present tense. No marketing language.
- **DS-03 Audience.** Write for an on-call engineer who has never seen the integration before.

## Required sections

Every integration has one wiki page per integration with these sections, in this order.

| Rule | Section | Must contain |
|---|---|---|
| DS-10 | **Overview** | Purpose in one or two sentences, source and target systems, business owner |
| DS-11 | **Data flow** | Trigger, message path from source to target, and frequency or schedule |
| DS-12 | **Interfaces** | Every endpoint, queue or topic the integration reads from or writes to |
| DS-13 | **Configuration** | Every configuration key with its purpose and default value; field mappings |
| DS-14 | **Error handling** | Retry policy (attempts, back-off), dead-letter handling and alerting |
| DS-15 | **Security** | Identities used, secrets location (Key Vault reference, never the value) and data classification |
| DS-16 | **Operations** | Where logs and dashboards are, and the runbook link |
| DS-17 | **Change log** | Date, change summary and the source (commit SHA or pull request) for each change |

## Evidence rules

- **DS-20 Evidence.** Every technical statement must be traceable to a source: code, IaC or configuration at a specific commit, a work item, or an ADR.
- **DS-21 Commit reference.** When documentation is updated because of a code change, the change log entry includes the commit SHA.
- **DS-22 Missing information.** If a required section can't be filled from the sources, write `Information missing:` followed by what is missing. Never guess.
- **DS-23 No secrets.** Never copy secret values, connection strings or personal data into documentation.

## Freshness

- **DS-30 Drift.** Documentation that contradicts the current code or configuration is a gap, even if it was correct before.
- **DS-31 Review.** An integration page is reviewed whenever its code, IaC or configuration changes.
