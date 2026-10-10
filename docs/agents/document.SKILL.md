# Document Agent — SKILL.md

> **The question it owns**
> *Which documents are ready to be produced, and from which template?*

Records become complete at unpredictable moments — a sync, a CSP's submission, an RM filling a gap. This agent notices that a record is now complete and hands it to the pipeline.

## At a glance

| | |
|---|---|
| Key | `document` |
| Schedule | Every 3 minutes |
| On by default | yes |
| Implementation | `backend/app/services/agents.py` — `@performs("document")` |
| Registered in | `backend/app/services/agent_registry.py` |

## What it does

- Finds records with everything their documents need
- Picks the active template for each configured document
- Hands the work to the existing deterministic pipeline
- Reports anything the pipeline refused, and why

## What it may do on its own

- Trigger generation for a record that is complete

## What it must ask a person about

- Nothing. Validation, placeholders, photo size and PDF conversion stay deterministic and are never overridden by an agent

## What it reads and writes

**Reads:** `csp_records`, `document_templates`, `processing_jobs`

**Writes:** `agent_findings`, `and triggers the existing pipeline`

## Things to be careful about

- It PROPOSES NOTHING, deliberately. Validation, placeholder replacement, photo sizing and PDF conversion are deterministic and are never overridden by an agent. The agent decides WHEN work happens, never WHETHER a document is correct.
- It runs every 3 minutes — the shortest interval of any agent — because the gap between 'complete' and 'issued' is the one a person notices.

## How it runs

It is a plain function taking a database session. It does not call any
other agent and no other agent calls it — they coordinate through the
database, not through each other. The runner records every pass in
`agent_runs`: when, who triggered it, what it concluded and how long it
took. A Super Admin can read that history on the Agents screen.

Scheduled runs happen once inside each active workspace, because an agent
reads workspace-scoped tables and would otherwise see nothing.

A disabled agent is not skipped silently — the run record says it was
switched off, which is the difference between "it found nothing" and "it
never looked".
