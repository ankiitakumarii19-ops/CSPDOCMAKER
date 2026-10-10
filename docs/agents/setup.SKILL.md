# Setup Agent — SKILL.md

> **The question it owns**
> *Is this workspace configured well enough to issue documents?*

A workspace is not ready to issue documents just because it exists. Its sheet has to be reachable, its columns have to map onto fields, its templates have to have every placeholder answered, and a document carrying a photograph has to say where the photograph goes. This agent answers 'what is still missing before this customer can go live' without anybody reading code.

## At a glance

| | |
|---|---|
| Key | `setup` |
| Schedule | On demand only — a person asks for it |
| On by default | yes |
| Implementation | `backend/app/services/agents.py` — `@performs("setup")` |
| Registered in | `backend/app/services/agent_registry.py` |

## What it does

- Reads each data source and reports whether it can be reached
- Compares the source's columns against the configured fields
- Reads every template and lists placeholders nothing fills
- Checks each document has a photo marker if it needs one
- Names what is still missing before the workspace can go live

## What it may do on its own

- Read configuration and report on it
- Record findings

## What it must ask a person about

- Mapping a source column to a field
- Mapping a template placeholder to a field
- Activating a template once everything it needs is mapped

## What it reads and writes

**Reads:** `data_sources`, `document_templates`, `csp_records`

**Writes:** `agent_findings`

## Things to be careful about

- It is the only agent that runs ON DEMAND rather than on a timer. Setup is something a person is doing, and findings from an hour ago are not useful while they are doing it.
- Its proposals change configuration — mapping a column, activating a template — so none of them is applied without a person accepting it. An agent that could quietly remap a placeholder could quietly print the wrong name on every certificate.

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
