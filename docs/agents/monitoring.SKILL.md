# Monitoring Agent — SKILL.md

> **The question it owns**
> *Is anything stuck, failing, or quietly not running?*

Everything else in this system reports what it did. Nothing reported what it failed to do, or stopped doing. A sync that quietly stopped running looks exactly like a sync with nothing to do.

## At a glance

| | |
|---|---|
| Key | `monitoring` |
| Schedule | Every 10 minutes |
| On by default | yes |
| Implementation | `backend/app/services/agents.py` — `@performs("monitoring")` |
| Registered in | `backend/app/services/agent_registry.py` |

## What it does

- Checks each data source synced when it should have
- Finds processing jobs that stopped part-way
- Counts failed sends and failed generations
- Watches the task queue for a backlog that is not clearing
- Notices an agent that has failed several times in a row

## What it may do on its own

- Record findings and raise their severity

## What it must ask a person about

- Disabling an agent that keeps failing

## What it reads and writes

**Reads:** `sync_runs`, `processing_jobs`, `email_jobs`, `agent_states`, `data_sources`

**Writes:** `agent_findings`

## Things to be careful about

- It is the ONLY agent that looks at the others, reading agent_states to spot one failing repeatedly. Even then it only proposes disabling it — it cannot switch another agent off.
- Its findings are the closest thing this system has to an alarm, so severity matters: critical means somebody should look now.

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
