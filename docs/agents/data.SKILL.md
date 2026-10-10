# Data Agent — SKILL.md

> **The question it owns**
> *Is every record complete, and if not, who should be asked?*

A record with a blank field cannot produce a document, and the useful question is never 'what is missing' but 'who can answer it'. This agent splits every gap by owner and routes it: the CSP's own details to the CSP, the hierarchy to their RM, and whatever the territory directory can settle to nobody at all.

## At a glance

| | |
|---|---|
| Key | `data` |
| Schedule | Every 15 minutes |
| On by default | yes |
| Implementation | `backend/app/services/agents.py` — `@performs("data")` |
| Registered in | `backend/app/services/agent_registry.py` |

## What it does

- Finds records with blank required fields
- Fills what the territory directory can answer, so nobody is asked
- Splits the rest into what the CSP owns and what their RM owns
- Raises an alert for the RM, and marks the CSP as needing asking
- Reports records nobody owns, which every RM can see

## What it may do on its own

- Fill a field from the directory when exactly one answer matches
- Raise and clear RM alerts

## What it must ask a person about

- Resolving a territory that matches more than one person
- A district spelling that nearly matches a known one

## What it reads and writes

**Reads:** `csp_records`, `the INFO sheet via info_directory`

**Writes:** `csp_records (only fields the directory settles)`, `rm_alerts`, `agent_findings`

## Things to be careful about

- It fills a field from the directory ONLY when exactly one row matches. A district that matches two is a proposal, not a guess — writing the wrong DC onto a record is worse than leaving it blank, because nothing afterwards would question it.
- Eight of the ten hierarchy fields are answered by the directory, so in practice only AO and RBO Name ever reach an RM.

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
