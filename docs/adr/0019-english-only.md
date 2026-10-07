# 0019. Everything in English

- **Status:** Accepted
- **Date:** 2026-10-06
- **Deciders:** P1, P2, P3
- **Related:** [0005](0005-generic-repo-with-fictional-data.md)

## Context

The repo is public and meant for an international audience. The agent's *output* language is a separate concern, because organisations document in their own language.

## Decision

- All repository content is in **English**: code, comments, docs, ADRs, issues, sample data and prompts.
- The **agent's output language** is set by the **swappable documentation standard** ([0005](0005-generic-repo-with-fictional-data.md)), not by the repo language.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Local language for docs/workshop | Limits reuse and contributions |
| Bilingual docs | Double maintenance |

## Consequences

- **Positive:** broad reuse and consistent contributions.
- **Negative:** workshops held in another language need the presenters to translate verbally.
